# BC Stack

This section covers the behavioral cloning neural network components.

## bc.py (310 lines)
Neural network for behavioral cloning.
- `BCNet` is a torch-free, pure Python implementation of a neural net.
- Uses `torch` only for tensor operations; all logic is in pure Python.
- `forward(x)` computes output with ReLU activation.
- `loss(pred, target)` computes MSE loss.
- `backward()` updates weights using gradient descent.
- `train_step()` performs one training step (batch forward + backward).
- Uses `data/` for loading datasets; imports `paths`, `regmc_db`.

## bc_train.py (120 lines)
Training pipeline for BC networks.
- `main()` loads dataset from `data/bc_dataset.json`.
- Uses `bc.BCNet` to train on batches of data.
- `train_epoch(net, data)` runs one epoch of training.
- `eval_loss(net, data)` computes validation loss.
- Imports `bc`, `paths`, `regmc_db`.

## bc_eval.py (85 lines)
Evaluation and inference for BC networks.
- `evaluate(net, team)` returns predicted move choice for a team.
- `predict_move(net, mon)` returns move probabilities for one mon.
- Uses `bc.BCNet` to compute predictions.
- Imports `bc`, `paths`, `regmc_db`.

## data/bc_dataset.json (200 lines)
Dataset for behavioral cloning training.
- Contains examples of teams and their optimal moves.
- Each example includes species, items, abilities, moves, EVs, nature.
- Used by `bc_train.py` to train neural networks.