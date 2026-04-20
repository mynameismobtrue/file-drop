import pandas as pd
import json

def extract_data(file_path):
    all_data = []
    
    # Ler as abas principais
    xls = pd.ExcelFile(file_path)
    
    # Aba: Variáveis CDP
    df_vars = pd.read_excel(xls, sheet_name='Variáveis CDP', skiprows=1)
    for _, row in df_vars.iterrows():
        if pd.isna(row['Nome']):
            continue
        all_data.append({
            'id': str(row.get('ID', '')),
            'nome': str(row.get('Nome', '')),
            'display_name': str(row.get('Display Name', '')),
            'significado': str(row.get('Variável', '')),
            'origem': str(row.get('Origem C360', '')),
            'campo_origem': str(row.get('Campo C360', '')),
            'exemplo_query': str(row.get('Regra', '')),
            'caso_uso': str(row.get('Ex. de Caso de Uso/Comentários', '')),
            'schema': str(row.get('Schema', '')),
            'path': str(row.get('Path', '')),
            'tipo_pessoa': str(row.get('Tipo Pessoa', ''))
        })

    # Aba: Eventos
    try:
        df_eventos = pd.read_excel(xls, sheet_name='Eventos')
        for _, row in df_eventos.iterrows():
            nome = row.get('Nome do Evento') or row.get('Nome')
            if pd.isna(nome):
                continue
            all_data.append({
                'id': 'Evento',
                'nome': str(nome),
                'display_name': str(row.get('Display Name', '')),
                'significado': str(row.get('Descrição', '')),
                'origem': 'Eventos CDP',
                'campo_origem': '',
                'exemplo_query': '',
                'caso_uso': '',
                'schema': 'Eventos',
                'path': '',
                'tipo_pessoa': ''
            })
    except Exception:
        pass

    return all_data

if __name__ == '__main__':
    data = extract_data('Dicionário-CDP(Adobe)-Copiar.xlsx')
    with open('cdp_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'Extraídos {len(data)} registros.')
