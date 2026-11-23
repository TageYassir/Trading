import pandas as pd
from zipp.glob import separate

data = pd.read_csv(r"C:\Users\fftt7\PyCharmMiscProject\Trading\Data_Visualisation\Data2.csv",sep=',')
print(data.head())
print(data.columns)