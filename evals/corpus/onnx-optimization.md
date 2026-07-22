# ONNX Runtime performance notes

## Quantization

Dynamic int8 quantization roughly halves model size and speeds up CPU
inference 1.5-3x with a small accuracy cost. Quantize the matmuls only;
leaving layernorm in fp32 avoids most of the quality drop. Always benchmark
against the fp32 export on your real inputs, not synthetic ones.

## Threading knobs

`intra_op_num_threads` controls parallelism inside an operator and matters
most for large matmuls; `inter_op_num_threads` rarely helps encoder models.
On a laptop, pinning intra-op to physical core count beats the default.

## Graph optimizations

Session option `ORT_ENABLE_ALL` fuses attention and gelu patterns at load
time. The first inference pays a warm-up cost; measure steady-state latency
after a few dozen calls, and cache the optimized graph to disk if startup
time matters.
