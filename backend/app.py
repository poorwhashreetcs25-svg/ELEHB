# Compatibility shim for Python 3.14 where pkgutil.get_loader was removed
import pkgutil
import importlib.util

if not hasattr(pkgutil, "get_loader"):
    def _get_loader(name):
        if name == "__main__":
            return None
        try:
            spec = importlib.util.find_spec(name)
            return spec.loader if spec else None
        except Exception:
            return None
    pkgutil.get_loader = _get_loader

from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage for items
items = []
next_id = 1

@app.route('/items', methods=['GET'])
def list_items():
    return jsonify(items)

@app.route('/items', methods=['POST'])
def create_item():
    global next_id
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    item = {'id': next_id, 'name': data['name']}
    next_id += 1
    items.append(item)
    return jsonify(item), 201

@app.route('/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    for item in items:
        if item['id'] == item_id:
            return jsonify(item)
    return jsonify({'error': 'Item not found'}), 404

@app.route('/items/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    for item in items:
        if item['id'] == item_id:
            item['name'] = data['name']
            return jsonify(item)
    return jsonify({'error': 'Item not found'}), 404

@app.route('/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    global items
    for item in items:
        if item['id'] == item_id:
            items = [i for i in items if i['id'] != item_id]
            return '', 204
    return jsonify({'error': 'Item not found'}), 404

if __name__ == '__main__':
    app.run(debug=True)
