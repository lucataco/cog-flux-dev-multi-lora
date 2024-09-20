# FLUX.1-dev multi-LoRA Explorer Cog Model

This is an implementation of [black-forest-labs/FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) as a [Cog](https://github.com/replicate/cog) model.

Named multi-LoRA Explorer, to explore the model with different LoRA weights.

## Development

Follow the [model pushing guide](https://replicate.com/docs/guides/push-a-model) to push your own model to [Replicate](https://replicate.com).


## How to use

Make sure you have [cog](https://github.com/replicate/cog) installed.

To run a prediction:

    cog predict -i prompt="a photo of TOK, sftsrv style" -i extra_loras=["lucataco/flux-queso","https://huggingface.co/alvdansen/softserve_anime/resolve/main/flux_dev_softstyle_araminta_k.safetensors"]

![Output](output.0.png)

## License

The code in this repository is licensed under the [Apache-2.0 License](LICENSE).

Flux Dev falls under the [`FLUX.1 [dev]` Non-Commercial License](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md).

`FLUX.1 [dev]` fine-tuned weights and their outputs are non-commercial by default, but can be used commercially when running on Replicate.