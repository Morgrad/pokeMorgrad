#!/usr/bin/env python3
"""Debug script to understand Taunt support move issue"""

import sys

sys.path.insert(0, '.')

from src import support_value as SV

# Test what happens when we parse effects and check if taunt is enabled
effects = SV.parse_effects("all")
print(f"Effects: {effects}")

# Test pure_enabled function directly
taunt_enabled = SV.pure_enabled("taunt", effects)
print(f"Taunt enabled with 'all' effects: {taunt_enabled}")

# Check what pure_kind returns for taunt
pk = SV.pure_kind("taunt")
print(f"Pure kind of taunt: {pk}")

# Check what effect_of returns for taunt
effect = SV.effect_of("taunt")
print(f"Effect of taunt: {effect}")

# Test with specific effects
test_effects = frozenset({"taunt"})
taunt_enabled2 = SV.pure_enabled("taunt", test_effects)
print(f"Taunt enabled with 'taunt' effect only: {taunt_enabled2}")

# Check EFFECTS tuple
print(f"EFFECTS: {SV.EFFECTS}")
