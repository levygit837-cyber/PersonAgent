"""Testes de integração da API de memória.

Usam TestClient do FastAPI para testar endpoints reais.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from personagent.interfaces.api.main import create_app


class TestMemoryAPI:
    """Testes da API REST de memória."""

    @pytest.fixture
    def client(self):
        """Cria um TestClient com app isolada."""
        app = create_app()
        return TestClient(app)

    def test_create_memory(self, client):
        """Testa criação de memória via API."""
        import uuid
        name = f"user_role_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/memory/test-project",
            json={
                "name": name,
                "description": "My role",
                "content": "I am a developer.",
                "memory_type": "user",
                "scope": "private",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert f"{name}.md" in data["path"]

    def test_create_memory_invalid_name(self, client):
        """Testa rejeição de nome inválido."""
        response = client.post(
            "/memory/test-project",
            json={
                "name": "My Bad Name",
                "description": "Bad",
                "content": "Content",
            },
        )
        assert response.status_code == 400
        assert "snake_case" in response.json()["detail"]

    def test_create_memory_empty_name(self, client):
        """Testa rejeição de nome vazio."""
        response = client.post(
            "/memory/test-project",
            json={
                "name": "",
                "description": "Bad",
                "content": "Content",
            },
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_create_memory_duplicate(self, client):
        """Testa rejeição de memória duplicada."""
        client.post(
            "/memory/test-project",
            json={
                "name": "unique_mem",
                "description": "First",
                "content": "Content",
            },
        )
        response = client.post(
            "/memory/test-project",
            json={
                "name": "unique_mem",
                "description": "Second",
                "content": "Content 2",
            },
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_get_memory(self, client):
        """Testa leitura de memória via API."""
        client.post(
            "/memory/test-project",
            json={
                "name": "read_test",
                "description": "Test",
                "content": "Hello world.",
            },
        )
        response = client.get("/memory/test-project/read_test")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "read_test"
        assert "Hello world" in data["content"]

    def test_get_memory_not_found(self, client):
        """Testa 404 para memória inexistente."""
        response = client.get("/memory/test-project/nonexistent")
        assert response.status_code == 404

    def test_get_memory_invalid_name(self, client):
        """Testa rejeição de nome inválido na leitura."""
        # Nome com .. não é válido como path param no FastAPI, mas testamos snake_case
        response = client.get("/memory/test-project/My%20Bad%20Name")
        assert response.status_code == 400
        assert "snake_case" in response.json()["detail"]

    def test_list_memories(self, client):
        """Testa listagem de memórias."""
        import uuid
        suffix = uuid.uuid4().hex[:8]
        client.post(
            f"/memory/list-test-{suffix}",
            json={"name": "mem_a", "description": "A", "content": "A"},
        )
        client.post(
            f"/memory/list-test-{suffix}",
            json={"name": "mem_b", "description": "B", "content": "B"},
        )
        response = client.get(f"/memory/list-test-{suffix}")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        names = {m["name"] for m in data["memories"]}
        assert names == {"mem_a", "mem_b"}

    def test_update_memory(self, client):
        """Testa atualização de memória."""
        client.post(
            "/memory/test-project",
            json={"name": "update_test", "description": "Old", "content": "Old content."},
        )
        response = client.put(
            "/memory/test-project/update_test",
            json={"description": "New", "content": "New content."},
        )
        assert response.status_code == 200

        # Verifica leitura
        read_response = client.get("/memory/test-project/update_test")
        data = read_response.json()
        assert data["description"] == "New"
        assert "New content" in data["content"]

    def test_delete_memory(self, client):
        """Testa deleção de memória."""
        client.post(
            "/memory/test-project",
            json={"name": "delete_test", "description": "Del", "content": "Del."},
        )
        response = client.delete("/memory/test-project/delete_test")
        assert response.status_code == 200

        # Verifica que foi deletado
        read_response = client.get("/memory/test-project/delete_test")
        assert read_response.status_code == 404

    def test_get_memory_index(self, client):
        """Testa leitura do MEMORY.md."""
        client.post(
            "/memory/test-project",
            json={"name": "idx_test", "description": "Idx", "content": "Idx."},
        )
        response = client.get("/memory/test-project/index")
        assert response.status_code == 200
        data = response.json()
        assert "Memory Index" in data["content"]
        assert "idx_test" in data["content"]

    def test_list_memories_filter_by_type(self, client):
        """Testa filtro por tipo de memória."""
        import uuid
        suffix = uuid.uuid4().hex[:8]
        client.post(
            f"/memory/filter-test-{suffix}",
            json={"name": "user_mem", "description": "U", "content": "U", "memory_type": "user"},
        )
        client.post(
            f"/memory/filter-test-{suffix}",
            json={"name": "proj_mem", "description": "P", "content": "P", "memory_type": "project"},
        )
        response = client.get(f"/memory/filter-test-{suffix}?memory_type=user")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["memories"][0]["name"] == "user_mem"

    def test_memory_index_route_order(self, client):
        """Testa que /index é acessível (não capturado por /{project_slug})."""
        # Cria uma memória chamada "index" para confundir
        client.post(
            "/memory/test-project",
            json={"name": "index", "description": "Idx", "content": "Idx."},
        )
        # O GET /index deve retornar o MEMORY.md, não a memória "index"
        response = client.get("/memory/test-project/index")
        assert response.status_code == 200
        assert "Memory Index" in response.json()["content"]
