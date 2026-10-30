from datasets import load_dataset
try:
    d = load_dataset('mohanty/PlantVillage', 'color', revision='9e97599868962bd0079b8db4b7f1efa9185fa1e7')
    print(d)
    print(d['train'].features)
except Exception as e:
    print(type(e).__name__ + ': ' + str(e))
