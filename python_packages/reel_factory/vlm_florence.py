import os
import torch
from transformers import AutoProcessor, AutoModelForCausalLM
import transformers
from PIL import Image

# Monkey-patch PreTrainedModel to fix transformers v5 compatibility with Florence-2
transformers.PreTrainedModel._supports_sdpa = False

_MODEL_ID = "microsoft/Florence-2-large"
_processor = None
_model = None

def _get_device():
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

def _load_model():
    global _processor, _model
    if _processor is None or _model is None:
        device = _get_device()
        print(f"Loading Florence-2-large on {device}...")
        
        # Florence-2 requires trust_remote_code=True
        _processor = AutoProcessor.from_pretrained(_MODEL_ID, trust_remote_code=True)
        # Load in fp16 if on mps or cuda
        dtype = torch.float16 if device in ("mps", "cuda") else torch.float32
        
        _model = AutoModelForCausalLM.from_pretrained(_MODEL_ID, trust_remote_code=True, torch_dtype=dtype)
        _model.to(device)
        _model.eval()

def generate_florence_caption(image_path: str) -> str:
    """Generate an ultra-detailed caption using Florence-2-large."""
    _load_model()
    device = _get_device()
    
    image = Image.open(image_path).convert("RGB")
    
    # Pad to square to avoid Florence-2 AssertionError
    w, h = image.size
    size = max(w, h)
    new_image = Image.new("RGB", (size, size), (0, 0, 0))
    new_image.paste(image, ((size - w) // 2, (size - h) // 2))
    image = new_image

    task_prompt = "<MORE_DETAILED_CAPTION>"
    
    inputs = _processor(text=task_prompt, images=image, return_tensors="pt")
    # Move inputs to device and convert float tensors to the correct dtype
    dtype = torch.float16 if device in ("mps", "cuda") else torch.float32
    for k, v in inputs.items():
        if isinstance(v, torch.Tensor):
            if v.dtype == torch.float32 or v.dtype == torch.float64:
                inputs[k] = v.to(device, dtype=dtype)
            else:
                inputs[k] = v.to(device)
                
    with torch.inference_mode():
        generated_ids = _model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            early_stopping=False,
            do_sample=False,
            num_beams=3,
        )
        
    generated_text = _processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    parsed_answer = _processor.post_process_generation(
        generated_text, 
        task=task_prompt, 
        image_size=(image.width, image.height)
    )
    
    return parsed_answer.get(task_prompt, generated_text)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(generate_florence_caption(sys.argv[1]))
    else:
        print("Usage: python vlm_florence.py <image_path>")
