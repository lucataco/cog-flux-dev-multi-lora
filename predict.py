# Prediction interface for Cog ⚙️
# https://github.com/replicate/cog/blob/main/docs/python.md

from cog import BasePredictor, Input, Path
import os
import re
import time
import torch
import subprocess
import numpy as np
from typing import Iterator
from diffusers import FluxPipeline
from weights import WeightsDownloadCache
from transformers import CLIPImageProcessor
from diffusers.pipelines.stable_diffusion.safety_checker import (
    StableDiffusionSafetyChecker
)

MODEL_CACHE = "checkpoints"
MODEL_URL = "https://weights.replicate.delivery/default/black-forest-labs/FLUX.1-dev/model-cache.tar"
SAFETY_CACHE = "safety-cache"
FEATURE_EXTRACTOR = "/src/feature-extractor"
SAFETY_URL = "https://weights.replicate.delivery/default/sdxl/safety-1.0.tar"

def download_weights(url, dest, file=False):
    start = time.time()
    print("downloading url: ", url)
    print("downloading to: ", dest)
    if not file:
        subprocess.check_call(["pget", "-x", url, dest], close_fds=False)
    else:
        subprocess.check_call(["pget", url, dest], close_fds=False)
    print("downloading took: ", time.time() - start)

class Predictor(BasePredictor):
    def setup(self) -> None:
        """Load the model into memory to make running multiple predictions efficient"""
        start = time.time()
        # Dont pull weights
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        self.weights_cache = WeightsDownloadCache()

        print("Loading safety checker...")
        if not os.path.exists(SAFETY_CACHE):
            download_weights(SAFETY_URL, SAFETY_CACHE)
        self.safety_checker = StableDiffusionSafetyChecker.from_pretrained(
            SAFETY_CACHE, torch_dtype=torch.float16
        ).to("cuda")
        self.feature_extractor = CLIPImageProcessor.from_pretrained(FEATURE_EXTRACTOR)
        
        print("Loading Flux txt2img Pipeline")
        if not os.path.exists(MODEL_CACHE):
            download_weights(MODEL_URL, MODEL_CACHE)
        self.txt2img_pipe = FluxPipeline.from_pretrained(
            "black-forest-labs/FLUX.1-dev",
            torch_dtype=torch.bfloat16,
            cache_dir=MODEL_CACHE
        ).to("cuda")

        # Save some VRAM by offloading the model to CPU
        vram = int(torch.cuda.get_device_properties(0).total_memory/(1024*1024*1024))
        if vram < 40:
            print("GPU VRAM < 40Gb - Offloading model to CPU")
            self.txt2img_pipe.enable_model_cpu_offload()
        
        print("setup took: ", time.time() - start)

    @torch.amp.autocast('cuda')
    def run_safety_checker(self, image):
        safety_checker_input = self.feature_extractor(image, return_tensors="pt").to("cuda")
        np_image = [np.array(val) for val in image]
        image, has_nsfw_concept = self.safety_checker(
            images=np_image,
            clip_input=safety_checker_input.pixel_values.to(torch.float16),
        )
        return image, has_nsfw_concept

    def aspect_ratio_to_width_height(self, aspect_ratio: str):
        aspect_ratios = {
            "1:1": (1024, 1024),"16:9": (1344, 768),"21:9": (1536, 640),
            "3:2": (1216, 832),"2:3": (832, 1216),"4:5": (896, 1088),
            "5:4": (1088, 896),"9:16": (768, 1344),"9:21": (640, 1536),
        }
        return aspect_ratios.get(aspect_ratio)

    def load_loras(self, hf_loras, lora_scales):
        # list of adapter names
        names = ['a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','v','w','x','y','z']
        count = 0
        # loop through each lora
        for hf_lora in hf_loras:
            # Check for Huggingface Slug lucataco/flux-emoji
            if re.match(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$", hf_lora):
                print(f"Downloading LoRA weights from - HF path: {hf_lora}")
                adapter_name = names[count]
                count += 1
                self.txt2img_pipe.load_lora_weights(hf_lora, adapter_name=adapter_name)
            # Check for Replicate tar file
            elif re.match(r"^https?://replicate.delivery/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/trained_model.tar", hf_lora):
                print(f"Downloading LoRA weights from - Replicate URL: {hf_lora}")
                local_weights_cache = self.weights_cache.ensure(hf_lora)
                lora_path = os.path.join(local_weights_cache, "output/flux_train_replicate/lora.safetensors")
                adapter_name = names[count]
                count += 1
                self.txt2img_pipe.load_lora_weights(lora_path, adapter_name=adapter_name)
            # Check for Huggingface URL
            elif re.match(r"^https?://huggingface.co", hf_lora):
                print(f"Downloading LoRA weights from - HF URL: {hf_lora}")
                huggingface_slug = re.search(r"^https?://huggingface.co/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)", hf_lora).group(1)
                weight_name = hf_lora.split('/')[-1]
                print(f"HuggingFace slug from URL: {huggingface_slug}, weight name: {weight_name}")
                adapter_name = names[count]
                count += 1
                self.txt2img_pipe.load_lora_weights(huggingface_slug, weight_name=weight_name)
            # Check for Civitai URL (like https://civitai.com/api/download/models/735262?type=Model&format=SafeTensor)
            elif re.match(r"^https?://civitai.com/api/download/models/[0-9]+\?type=Model&format=SafeTensor", hf_lora):
                # split url to get first part of the url, everythin before '?type'
                civitai_slug = hf_lora.split('?type')[0]
                print(f"Downloading LoRA weights from - Civitai URL: {civitai_slug}")
                lora_path = self.weights_cache.ensure(hf_lora, file=True)
                adapter_name = names[count]
                count += 1
                self.txt2img_pipe.load_lora_weights(lora_path, adapter_name=adapter_name)
            # Check for URL to a .safetensors file
            elif hf_lora.endswith('.safetensors'):
                print(f"Downloading LoRA weights from - safetensor URL: {hf_lora}")
                try:
                    lora_path = self.weights_cache.ensure(hf_lora, file=True)
                except Exception as e:
                    print(f"Error downloading LoRA weights: {e}")
                    continue
                adapter_name = names[count]
                count += 1
                self.txt2img_pipe.load_lora_weights(lora_path, adapter_name=adapter_name)
            else:
                raise Exception(f"Invalid lora, must be either a: HuggingFace path, Replicate model.tar, or a URL to a .safetensors file: {hf_lora}")
        
        adapter_names = names[:count]
        adapter_weights = lora_scales[:count]
        # print(f"adapter_names: {adapter_names}")
        # print(f"adapter_weights: {adapter_weights}")
        self.txt2img_pipe.set_adapters(adapter_names, adapter_weights=adapter_weights)
            
    @torch.inference_mode()
    def predict(
        self,
        prompt: str = Input(description="Prompt for generated image"),
        aspect_ratio: str = Input(
            description="Aspect ratio for the generated image",
            choices=["1:1", "16:9", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21"],
            default="1:1"),
        num_outputs: int = Input(
            description="Number of images to output.",
            ge=1,
            le=4,
            default=1,
        ),
        num_inference_steps: int = Input(
            description="Number of inference steps",
            ge=1,le=50,default=28,
        ),
        guidance_scale: float = Input(
            description="Guidance scale for the diffusion process",
            ge=0,le=10,default=3.5,
        ),
        seed: int = Input(description="Random seed. Set for reproducible generation", default=None),
        output_format: str = Input(
            description="Format of the output images",
            choices=["webp", "jpg", "png"],
            default="webp",
        ),
        output_quality: int = Input(
            description="Quality when saving the output images, from 0 to 100. 100 is best quality, 0 is lowest quality. Not relevant for .png outputs",
            default=80,
            ge=0,
            le=100,
        ),
        hf_loras: list[str] = Input(
            description="Huggingface path, or URL to the LoRA weights. Ex: alvdansen/frosting_lane_flux",
            default=None,
        ),
        lora_scales: list[float] = Input(
            description="Scale for the LoRA weights. Default value is 0.8",
            default=None,
        ),
        disable_safety_checker: bool = Input(
            description="Disable safety checker for generated images. This feature is only available through the API. See [https://replicate.com/docs/how-does-replicate-work#safety](https://replicate.com/docs/how-does-replicate-work#safety)",
            default=False,
        ),
    ) -> Iterator[Path]:
        """Run a single prediction on the model"""
        if seed is None:
            seed = int.from_bytes(os.urandom(2), "big")
        print(f"Using seed: {seed}")

        width, height = self.aspect_ratio_to_width_height(aspect_ratio)
        max_sequence_length=512
        
        flux_kwargs = {}
        print(f"Prompt: {prompt}")
        print("txt2img mode")
        flux_kwargs["width"] = width
        flux_kwargs["height"] = height
        pipe = self.txt2img_pipe
        if hf_loras:
            flux_kwargs["joint_attention_kwargs"] = {"scale": 1.0}
            
        # Check for hf_loras and lora_scales 
        if hf_loras and not lora_scales:
            # If no lora_scales are provided, use 0.8 for each lora
            lora_scales = [0.8] * len(hf_loras)
            self.load_loras(hf_loras, lora_scales)
        elif hf_loras and len(lora_scales) == 1:
            # If only one lora_scale is provided, use it for all loras
            lora_scales = [lora_scales[0]] * len(hf_loras)
            self.load_loras(hf_loras, lora_scales)
        elif hf_loras and len(lora_scales) >= len(hf_loras):
            # If lora_scales are provided, use them for each lora
            self.load_loras(hf_loras, lora_scales)
        else:
            flux_kwargs["joint_attention_kwargs"] = None
            pipe.unload_lora_weights()

        generator = torch.Generator("cuda").manual_seed(seed)

        common_args = {
            "prompt": [prompt] * num_outputs,
            "guidance_scale": guidance_scale,
            "generator": generator,
            "num_inference_steps": num_inference_steps,
            "max_sequence_length": max_sequence_length,
            "output_type": "pil"
        }

        output = pipe(**common_args, **flux_kwargs)

        if hf_loras is not None:
            self.txt2img_pipe.unload_lora_weights()

        if not disable_safety_checker:
            _, has_nsfw_content = self.run_safety_checker(output.images)

        output_paths = []
        for i, image in enumerate(output.images):
            if not disable_safety_checker and has_nsfw_content[i]:
                print(f"NSFW content detected in image {i}")
                continue
            output_path = f"/tmp/out-{i}.{output_format}"
            if output_format != 'png':
                image.save(output_path, quality=output_quality, optimize=True)
            else:
                image.save(output_path)
            output_paths.append(Path(output_path))

        if len(output_paths) == 0:
            raise Exception("NSFW content detected. Try running it again, or try a different prompt.")

        return output_paths
    