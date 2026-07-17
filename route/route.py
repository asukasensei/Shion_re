from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer


@dataclass(frozen=True)
class RouteLabel:
    label: str | int
    confidence: float
    accepted: bool


@dataclass(frozen=True)
class RouteResult:
    emotion: RouteLabel
    scene: RouteLabel
    intensity: RouteLabel
    raw: dict[str, Any]


class RouteHeads(nn.Module):
    def __init__(self, hidden_size: int, emotion_count: int, scene_count: int, intensity_count: int):
        super().__init__()
        self.emotion_head = nn.Linear(hidden_size, emotion_count)
        self.scene_head = nn.Linear(hidden_size, scene_count)
        self.intensity_head = nn.Linear(hidden_size, intensity_count)


class BGERouteClassifier:
    def __init__(self, model_dir: str | Path = "route/bge_router_v3", threshold: float = 0.4):
        self.model_dir = Path(model_dir)
        self.threshold = threshold

        with (self.model_dir / "router_config.json").open("r", encoding="utf-8") as f:
            self.router_config = json.load(f)

        self.emotion_labels = self.router_config["emotion_labels"]
        self.scene_labels = self.router_config["scene_labels"]

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir / "backbone")
        self.backbone = AutoModel.from_pretrained(self.model_dir / "backbone")
        self.backbone.eval()

        state = torch.load(self.model_dir / "heads.pt", map_location="cpu", weights_only=True)
        hidden_size = self.backbone.config.hidden_size

        self.heads = RouteHeads(
            hidden_size=hidden_size,
            emotion_count=state["emotion_head"]["weight"].shape[0],
            scene_count=state["scene_head"]["weight"].shape[0],
            intensity_count=state["intensity_head"]["weight"].shape[0],
        )
        self.heads.emotion_head.load_state_dict(state["emotion_head"])
        self.heads.scene_head.load_state_dict(state["scene_head"])
        self.heads.intensity_head.load_state_dict(state["intensity_head"])
        self.heads.eval()

    @torch.inference_mode()
    def predict(self, text: str) -> RouteResult:
        inputs = self.tokenizer(
            text or "",
            truncation=True,
            max_length=self.router_config.get("max_length", 96),
            padding=False,
            return_tensors="pt",
        )
        outputs = self.backbone(**inputs)
        pooled = outputs.last_hidden_state[:, 0]

        emotion = self._pick(self.heads.emotion_head(pooled), self.emotion_labels)
        scene = self._pick(self.heads.scene_head(pooled), self.scene_labels)
        intensity = self._pick(self.heads.intensity_head(pooled), list(range(self.heads.intensity_head.out_features)))

        return RouteResult(
            emotion=emotion,
            scene=scene,
            intensity=intensity,
            raw={
                "emotion": emotion.__dict__,
                "scene": scene.__dict__,
                "intensity": intensity.__dict__,
            },
        )

    def _pick(self, logits: torch.Tensor, labels: list[Any]) -> RouteLabel:
        probs = torch.softmax(logits[0], dim=-1)
        confidence, index = torch.max(probs, dim=-1)
        label = labels[int(index)]
        score = float(confidence)
        return RouteLabel(label=label, confidence=score, accepted=score > self.threshold)