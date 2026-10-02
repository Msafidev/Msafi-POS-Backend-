# No models — this app is pure read-side aggregation over Sale, SaleItem,
# Expense, and Product (all owned by their respective apps). Keeping it
# model-free avoids a migration dependency tangle across four other apps.
