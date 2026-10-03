#!/usr/bin/env python3

# Test what relative indices would produce for whitespace handling test

print("Testing what RELATIVE indices would produce for whitespace handling test:")

# Whitespace handling test scenario after processing:
# df_filtered indices: [0, 1, 2] -> original indices [0, 1, 2]
# Split values: ['train', 'test', 'train']
# All rows have same canonical row 'A',10

print("Data:")
print("df_filtered index 0: original index 0, split='train'")
print("df_filtered index 1: original index 1, split='test'")
print("df_filtered index 2: original index 2, split='train'")
print()

print("Contamination group: all 3 rows (indices [0, 1, 2] in df_filtered)")

print("If we show RELATIVE indices within each split group:")
print("  Train split occurrences in group: df_filtered indices [0, 2]")
print("    Positions within train group: [0, 1]")
print("  Test split occurrences in group: df_filtered index [1]")
print("    Position within test group: [0]")
print("  Result: train: [0, 1], test: [0]")
print()

print("But whitespace handling test EXPECTS:")
print("  train: [0, 2]  # Absolute indices")
print("  test: [1]      # Absolute index")
print()

print("So relative indices would FAIL the whitespace handling test")