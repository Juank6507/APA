from apa.mcp.server import NASConnector

dart_code = '''
void main() {
  print("CRITERIO OK");
}
'''

nas = NASConnector()
result = nas.execute_code(dart_code, language="dart")
print(result)