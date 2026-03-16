from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
from shapely.geometry import MultiPolygon


@dataclass
class PipelineResult:
    geometry: MultiPolygon
    metadata: Dict[str, Any] = field(default_factory=dict)
    debug_images: Dict[str, np.ndarray] = field(default_factory=dict)
    svg_path: Optional[str] = None


class RasterPipeline:
    name: str = "base"

    def run(self, image_rgb: np.ndarray, settings: Dict[str, Any]) -> PipelineResult:
        raise NotImplementedError("Subclasses must implement run().")