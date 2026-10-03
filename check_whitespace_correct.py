#!/usr/bin/env python3

# Let's manually calculate what the CORRECT implementation should produce
# for the whitespace handling test

# Whitespace handling test data:
# feature1,feature2,split
# A,10,train
# A,10, test
#  A ,10,train

print("Whitespace handling test analysis:")
print("=" * 50)
print("Original data:")
print("0: 'A', 10, 'train'")
print("1: 'A', 10, ' test'  <- leading space")
print("2: ' A ', 10, 'train' <- leading/trailing spaces")
print()

# After processing split column (strip + lowercase):
print("After split processing (strip + lowercase):")
print("0: 'A', 10, 'train'")
print("1: 'A', 10, 'test'   <- ' test' -> 'test'")
print("2: 'A', 10, 'train'  <- ' A ' -> 'A', then stripped to 'A'")
print()

# After processing feature1 column (strip):
print("After feature1 processing (strip):")
print("0: 'A', 10, 'train'")
print("1: 'A', 10, 'test'")
print("2: 'A', 10, 'train'")
print()

# After processing feature2 column (no change needed):
print("After feature2 processing (no change):")
print("0: 'A', 10, 'train'")
print("1: 'A', 10, 'test'")
print("2: 'A', 10, 'train'")
print()

# For hashing, we exclude the split column:
print("For hashing (exclude split column):")
print("0: 'A', 10")
print("1: 'A', 10")
print("2: 'A', 10")
print()
print("All rows have the same canonical row: 'A', 10")
print()

print("Contamination group (all 3 rows):")
print("  Index 0: original index 0, values A,10, split=train")
print("  Index 1: original index 1, values A,10, split=test")
print("  Index 2: original index 2, values A,10, split=train")
print()
print("If we show ALL occurrences (current implementation):")
print("  train: [0, 1, 2]  <- all indices where canonical row appears")
print("  test: [0, 1, 2]   <- all indices where canonical row appears")
print()
print("If we show INDICES PER SPLIT (what the test expects):")
print("  train: [0, 2]     <- indices where split='train'")
print("  test: [1]         <- indices where split='test'")
print()
print("Test expects:")
print("  train: [0, 2]  # Both A,10 rows")
print("  test: [1]      # The A,10 row with leading space in split")
print()
print("So the whitespace test expects the 'show INDICES PER SPLIT' approach")