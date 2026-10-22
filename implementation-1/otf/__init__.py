"""OTF: on-the-fly tool generation for document question answering.

The package is document-agnostic by construction: it reads structure (outline, lines, tables) from a
PDF and asks the model to write the tools. tests/test_no_benchmark_words.py keeps benchmark-specific
vocabulary out of this package.
"""
