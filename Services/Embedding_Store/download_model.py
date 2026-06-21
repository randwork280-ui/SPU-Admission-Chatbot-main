import os
from FlagEmbedding import BGEM3FlagModel

def download_model():
    model_name = "BAAI/bge-m3"
    print(f"Downloading model: {model_name}...")
    
    # Initialize model to trigger download
    # We don't need GPU here, just download the files
    _ = BGEM3FlagModel(
        model_name,
        use_fp16=False,
        device="cpu"
    )
    
    print("Model downloaded successfully!")

if __name__ == "__main__":
    download_model()
