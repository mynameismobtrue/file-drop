# Dicionário CDP Adobe

Site estático para consulta de atributos do Dicionário CDP Adobe.

## Arquivos principais

- `index.html`: página do site com busca e modal de detalhes.
- `cdp_data.json`: base de dados usada pelo site.
- `extract_data.py`: script para gerar o `cdp_data.json` a partir do Excel `Dicionário-CDP(Adobe)-Copiar.xlsx`.

## Como publicar no GitHub Pages

1. Entre no repositório no GitHub.
2. Vá em **Settings**.
3. Vá em **Pages**.
4. Em **Build and deployment**, selecione **Deploy from a branch**.
5. Escolha a branch **main** e a pasta **/ root**.
6. Clique em **Save**.

Depois disso, o site deve ficar disponível no endereço do GitHub Pages do repositório.

## Importante

O arquivo `cdp_data.json` atual é temporário. Para ativar a base completa, substitua esse arquivo pelo `cdp_data.json` completo gerado a partir do Excel original.

Para gerar localmente:

```bash
pip install pandas openpyxl
python extract_data.py
```

Depois, faça upload do `cdp_data.json` completo na raiz do repositório, substituindo o arquivo temporário.
