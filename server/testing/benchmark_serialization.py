
import json
import time
import base64
import numpy as np
import random

def benchmark_serialization():
    # Simulate a BGE-M3 embedding (1024 float32 values)
    embedding = [random.uniform(-1, 1) for _ in range(1024)]
    embedding_np = np.array(embedding, dtype=np.float32)
    
    print(f"--- Benchmarking 1000 iterations for 1024-dim vector ---")
    
    # JSON Benchmark
    start = time.time()
    for _ in range(1000):
        s = json.dumps(embedding)
        d = json.loads(s)
    json_time = (time.time() - start) * 1000
    print(f"JSON: {json_time:.2f}ms (Total), {json_time/1000:.4f}ms per op")
    
    # Binary (Base64) Benchmark
    start = time.time()
    for _ in range(1000):
        s = base64.b64encode(embedding_np.tobytes()).decode('ascii')
        d = np.frombuffer(base64.b64decode(s), dtype=np.float32).tolist()
    bin_time = (time.time() - start) * 1000
    print(f"Binary (B64): {bin_time:.2f}ms (Total), {bin_time/1000:.4f}ms per op")
    
    improvement = json_time / bin_time
    print(f"\nSpeed improvement: {improvement:.1f}x")
    
    # Size Comparison
    json_size = len(json.dumps(embedding))
    bin_size = len(base64.b64encode(embedding_np.tobytes()).decode('ascii'))
    print(f"Size - JSON: {json_size} bytes, Binary: {bin_size} bytes ({((json_size-bin_size)/json_size)*100:.1f}% reduction)")

if __name__ == "__main__":
    benchmark_serialization()
