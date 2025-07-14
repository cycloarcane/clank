"""ONNX model wrapper for Moonshine ASR using official moonshine-onnx library."""

import os
import hashlib

def _verify_model_integrity(models_dir):
    """Verify SHA256 checksums of model files before loading.
    
    Args:
        models_dir: Directory containing the model files
        
    Returns:
        bool: True if all checksums match, False otherwise
        
    Raises:
        FileNotFoundError: If model files or SHA256SUMS are missing
        ValueError: If checksums don't match
    """
    sha256sums_path = os.path.join(models_dir, "..", "..", "SHA256SUMS")
    
    if not os.path.exists(sha256sums_path):
        raise FileNotFoundError(f"SHA256SUMS not found at {sha256sums_path}")
    
    expected_hashes = {}
    with open(sha256sums_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                hash_val, file_path = line.split(None, 1)
                expected_hashes[file_path] = hash_val
    
    # Check model files
    model_files = ["models/moonshine/encoder_model.onnx", "models/moonshine/decoder_model_merged.onnx"]
    
    for file_path in model_files:
        if file_path not in expected_hashes:
            raise ValueError(f"No expected hash found for {file_path}")
        
        full_path = os.path.join(models_dir, "..", "..", file_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Model file not found: {full_path}")
        
        # Calculate actual hash
        hasher = hashlib.sha256()
        with open(full_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        
        if actual_hash != expected_hashes[file_path]:
            raise ValueError(f"SHA256 mismatch for {file_path}: expected {expected_hashes[file_path]}, got {actual_hash}")
    
    return True

class MoonshineOnnxModel(object):
    def __init__(self, models_dir=None, model_name=None):
        """Initialize Moonshine ONNX model using official moonshine-onnx library.
        
        Args:
            models_dir: Directory containing local model files (optional)
            model_name: Model name for fallback (unused when models_dir is provided)
        """
        import moonshine_onnx
        
        if models_dir is not None:
            # Verify model integrity before loading
            _verify_model_integrity(models_dir)
            
            # Use official moonshine-onnx with local models
            # The library still needs a model_name even when using local models
            fallback_model_name = model_name or "moonshine/base"
            self._model = moonshine_onnx.MoonshineOnnxModel(models_dir=models_dir, model_name=fallback_model_name)
        else:
            # Fallback to downloading if no local models
            self._model = moonshine_onnx.MoonshineOnnxModel(model_name=model_name)

    def generate(self, audio, max_len=None):
        """Generate transcription from audio using official moonshine-onnx.
        
        Args:
            audio: Numpy array of shape [1, num_audio_samples]
            max_len: Maximum length of generated sequence (optional)
        """
        # Use the official model's generate method directly
        return self._model.generate(audio, max_len)