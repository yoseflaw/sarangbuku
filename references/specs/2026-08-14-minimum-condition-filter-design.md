# Minimum Condition Filter Design

## Goal

Make the Temukan condition filter represent the lowest acceptable physical condition instead of an exact condition.

## Behavior

Conditions retain their existing best-to-worst order:

1. Seperti Baru
2. Sangat Bagus
3. Masih Bagus
4. Cukup Bagus
5. Sudah Buruk

Selecting a condition includes copies at that condition and every better condition. For example, selecting `Cukup Bagus` includes `Cukup Bagus`, `Masih Bagus`, `Sangat Bagus`, and `Seperti Baru`, while excluding `Sudah Buruk`. Leaving the filter empty includes every condition.

The filter label becomes `Kondisi minimum` so the threshold behavior is clear. The filter omits `Sudah Buruk` because that threshold includes every condition and is therefore identical to `Semua kondisi`; `Sudah Buruk` remains a valid condition for owned copies.

## Implementation

Use the existing order of `BookCopy.Condition.choices`. Find the selected value and filter with `condition__in` over that value and all preceding values. Keep existing invalid-choice validation and fail-closed discovery behavior unchanged.

No model, database, or migration changes are needed.

## Verification

Add one discovery regression test proving that the selected condition and better conditions appear while a worse condition does not. Existing composition, invalid-filter, privacy, and discovery tests must continue to pass.
