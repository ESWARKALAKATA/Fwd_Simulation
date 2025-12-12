from typing import List, Dict, Any
import httpx
from app.config import settings

class ModelRegistry:
    def __init__(self):
        self.models = []
        self._register_models()

    def _register_models(self):
        # 1. OpenRouter (Default)
        if settings.OPENROUTER_API_KEY:
            self.models.append({
                "id": "openrouter:default",
                "provider": "openrouter",
                "label": "OpenRouter Default (Cheap)",
                "default_usage": "general"
            })

        # 2. Ollama (Dynamic)
        if settings.OLLAMA_BASE_URL:
            try:
                # Attempt to fetch models from Ollama
                # We use a short timeout so we don't block startup too long
                with httpx.Client(timeout=2.0) as client:
                    resp = client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        for model in data.get("models", []):
                            name = model.get("name")
                            self.models.append({
                                "id": f"ollama:{name}",
                                "provider": "ollama",
                                "label": f"Ollama {name} (Local)",
                                "default_usage": "local"
                            })
            except Exception as e:
                print(f"Could not fetch Ollama models: {e}")
                # Fallback if fetch fails but URL is set
                self.models.append({
                    "id": "ollama:llama3",
                    "provider": "ollama",
                    "label": "Ollama Llama 3 (Local - Fallback)",
                    "default_usage": "local"
                })

        # 3. Gemini
        if settings.GEMINI_API_KEY:
            self.models.append({
                "id": "gemini:gemini-2.0-flash-exp",
                "provider": "gemini",
                "label": "Gemini 2.0 Flash (Experimental)",
                "default_usage": "general"
            })
            self.models.append({
                "id": "gemini:gemini-2.0-flash-lite-exp",
                "provider": "gemini",
                "label": "Gemini 2.0 Flash-Lite (Experimental)",
                "default_usage": "general"
            })

        # 4. OpenAI
        if settings.OPENAI_API_KEY:
            self.models.append({
                "id": "openai:gpt-4o-mini",
                "provider": "openai",
                "label": "OpenAI GPT-4o mini (cheap default)",
                "default_usage": "general"
            })

    def list_models(self) -> List[Dict[str, Any]]:
        return self.models

    def get_model_info(self, model_id: str) -> Dict[str, Any]:
        for m in self.models:
            if m["id"] == model_id:
                return m
        return None

registry = ModelRegistry()
