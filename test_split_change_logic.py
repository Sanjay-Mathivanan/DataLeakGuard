#!/usr/bin/env python3

import pandas as pd
import numpy as np

# Test the whitespace handling case
print("Testing whitespace handling case:")
df = pd.DataFrame({
    'feature1': ['A', 'A', ' A '],
    'feature2': [10, 10, 10],
    'split': ['train', ' test', 'train']
})

print(f"Original split column: {df['split'].tolist()}")
split_column = 'split'

# New logic: Compare original values (for kept rows) vs processed values (for kept rows)
# Step 1: Create processed version (what split_series becomes)
split_series = df[split_column].copy()
split_series = split_series.where(
    split_series.isnull(),
    split_series.astype(str).str.strip().str.lower()
)
print(f"After processing (strip + lower): {split_series.tolist()}")

# Step 2: Create mask for non-empty values (what non_empty_split_mask becomes)
non_empty_split_mask = split_series.notna() & (split_series != '')
print(f"Non-empty mask: {non_empty_split_mask.tolist()}")

# Step 3: Get original values for kept rows and processed values for kept rows
original_values_kept = df[split_column][non_empty_split_mask]
processed_values_kept = split_series[non_empty_split_mask]
print(f"Original values for kept rows: {original_values_kept.tolist()}")
print(f"Processed values for kept rows: {processed_values_kept.tolist()}")

# Step 4: Compare them
split_values_changed = not original_values_kept.equals(processed_values_kept)
print(f"Split values changed: {split_values_changed}")

print()

# Test the basic contamination case
print("Testing basic contamination case:")
df2 = pd.DataFrame({
    'id': [1, 2, 3, 4, 5],
    'feature1': ['A', 'B', 'C', 'A', 'D'],
    'feature2': [10, 20, 30, 10, 40],
    'split': ['train', 'train', 'test', 'test', 'train']
})

print(f"Original split column: {df2[split_column].tolist()}")
split_column = 'split'

# New logic
split_series = df2[split_column].copy()
split_series = split_series.where(
    split_series.isnull(),
    split_series.astype(str).str.strip().str.lower()
)
print(f"After processing (strip + lower): {split_series.tolist()}")

non_empty_split_mask = split_series.notna() & (split_series != '')
print(f"Non-empty mask: {non_empty_split_mask.tolist()}")

original_values_kept = df2[split_column][non_empty_split_mask]
processed_values_kept = split_series[non_empty_split_mask]
print(f"Original values for kept rows: {original_values_kept.tolist()}")
print(f"Processed values for kept rows: {processed_values_kept.tolist()}")

split_values_changed = not original_values_kept.equals(processed_values_kept)
print(f"Split values changed: {split_values_changed}")