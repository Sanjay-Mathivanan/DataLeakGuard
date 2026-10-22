def test_preview_rows(client):
    csv_content = b'name,age,feature\nAlice,30,1\nBob,25,2\nCharlie,35,3\nDavid,40,4\n'
    response = client.post(
        '/api/v1/datasets',
        data={
            'name': 'preview test',
            'type': 'tabular',
            'format': 'CSV',
            'description': 'test'
        },
        files={'file': ('test.csv', csv_content, 'text/csv')}
    )
    print('Response status:', response.status_code)
    data = response.json()
    print('Response data:')
    for key, value in data.items():
        if key in ['preview_rows', 'columns', 'profile']:
            print(f'  {key}: {value}')
        else:
            print(f'  {key}: {value}')
    # Assertions
    assert data['preview_rows'] is not None
