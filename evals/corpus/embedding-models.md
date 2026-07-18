# Choosing text embedding models

## Dimensions and storage

Output width is a cost knob: 384-dim vectors halve index memory versus
768-dim, and for corpora under a million chunks the recall difference is
usually small. Matryoshka-trained models let you truncate vectors after the
fact and renormalize.

## Pooling and prefixes

BERT-style encoders need mean pooling over the attention mask unless the
export already emits a sentence embedding. Retrieval-tuned models are often
asymmetric: the query side expects an instruction prefix while documents are
embedded bare — skipping the prefix silently costs recall.

## Sequence length

Most small encoders cap at 512 tokens. Chunk your documents below the cap
rather than letting the tokenizer truncate, because truncation eats the end
of the text where conclusions tend to live.
