import torch
import torch.nn as nn
import pandas as pd

# Load the data chunk assigned to this worker
df = pd.read_csv('data.csv')
print(f"Training on {len(df)} rows, {df.shape[1] - 1} features")

# Separate features and target (last column is the label)
X = torch.tensor(df.iloc[:, :-1].values, dtype=torch.float32)
y = torch.tensor(df.iloc[:, -1].values, dtype=torch.float32).unsqueeze(1)

# Simple linear regression model
model = nn.Linear(X.shape[1], 1)
optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
loss_fn = nn.MSELoss()

# Train for 20 steps
for epoch in range(20):
    pred = model(X)
    loss = loss_fn(pred, y)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    if epoch % 5 == 0:
        print(f"  Epoch {epoch}: loss={loss.item():.4f}")

print(f"Final loss: {loss.item():.4f}")

# Save the trained weights — the worker uploads this file to Supabase
torch.save(model.state_dict(), 'model.pth')
print("Saved model.pth")
