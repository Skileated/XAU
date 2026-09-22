"""Derive feature-family counts directly from FeatureRegistry."""

from xau_quant.features.registry import FeatureRegistry

registry = FeatureRegistry()

all_features = registry.get_ordered_features()
fixed_metadata = registry.get_fixed_metadata_column_specs()
all_schema = registry.get_full_schema_column_specs()

print(f"Total registered feature definitions: {len(all_features)}")
print(f"Total fixed metadata columns: {len(fixed_metadata)}")
print(f"Total full schema columns: {len(all_schema)}")
print(f"Max required history bars: {registry.max_required_history_bars()}")

print("\n" + "=" * 90)
print(f"{'Family':<18} {'Def Count':<12} {'Col Count':<12} {'Min Hist':<10} {'Max Hist':<10} {'Max Feature'}")
print("=" * 90)

families = sorted(list(set(f.family for f in all_features)))

total_defs = 0
total_cols = 0

for fam in families:
    fams = [f for f in all_features if f.family == fam]
    def_cnt = len(fams)
    col_cnt = sum(len(f.columns) for f in fams)
    min_h = min(f.required_history_bars for f in fams)
    max_h = max(f.required_history_bars for f in fams)
    max_feat = [f.name for f in fams if f.required_history_bars == max_h][0]

    total_defs += def_cnt
    total_cols += col_cnt
    print(f"{fam:<18} {def_cnt:<12} {col_cnt:<12} {min_h:<10} {max_h:<10} {max_feat}")


print("=" * 80)
print(f"{'TOTAL FEATURES':<18} {total_defs:<12} {total_cols:<12}")
print(f"{'FIXED METADATA':<18} {'-':<12} {len(fixed_metadata):<12}")
print(f"{'FULL SCHEMA TOTAL':<18} {'-':<12} {len(fixed_metadata) + total_cols:<12}")
print("=" * 80)

# List fixed metadata columns
print("\nFixed Metadata Columns (12):")
for col in fixed_metadata:
    print(f"  - {col.name} ({col.duckdb_type}, nullable={col.nullable})")
