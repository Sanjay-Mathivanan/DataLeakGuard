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
    assert response.status_code == 201
    data = response.json()
    print('Response keys:', list(data.keys()))
    print('preview_rows:', data.get('preview_rows'))
    print('columns:', data.get('columns'))
    print('sample_count:', data.get('sample_count'))
    print('feature_count:', data.get('feature_count'))
    # Assertions
    assert data['preview_rows'] is not None
    assert len(data['preview_rows']) == 4  # 4 rows
    assert data['columns'] is not None
    assert len(data['columns']) == 3  # name, age, feature
    # Check that each column has the expected keys
    for col in data['columns']:
        assert 'name' in col
        assert 'type' in col
        assert 'missingCount' in col
        assert 'uniqueCount' in col
    # Check that the first row has the expected values
    row0 = data['preview_rows'][0]
    assert row0['name'] == 'Alice'
    assert row0['age'] == 30
    assert row0['feature'] == 1
