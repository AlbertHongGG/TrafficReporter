from __future__ import annotations

import importlib.util
import sys
import urllib.request
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure

from .dependencies import DependencyRegistry


_ARCH_URL = 'https://raw.githubusercontent.com/csguoh/MambaIR/main/basicsr/archs/mambairv2light_arch.py'
_ARCH_MODULE_NAME = 'traffic_lpr_runtime._vendor.mambairv2light_arch'
_WEIGHT_SPECS = {
    2: {
        'filename': 'mambairv2_lightSR_x2.pth',
        'url': 'https://huggingface.co/cguoh/MambaIR/resolve/main/MambaIRv2_ckpt/mambairv2_lightSR_x2.pth?download=true',
    },
    4: {
        'filename': 'mambairv2_lightSR_x4.pth',
        'url': 'https://huggingface.co/cguoh/MambaIR/resolve/main/MambaIRv2_ckpt/mambairv2_lightSR_x4.pth?download=true',
    },
}
_LIGHT_CONFIG = {
    'img_size': 64,
    'patch_size': 1,
    'in_chans': 3,
    'embed_dim': 48,
    'd_state': 8,
    'depths': (5, 5, 5, 5),
    'num_heads': (4, 4, 4, 4),
    'window_size': 16,
    'inner_rank': 32,
    'num_tokens': 64,
    'convffn_kernel_size': 5,
    'mlp_ratio': 1.0,
    'img_range': 1.0,
    'upsampler': 'pixelshuffledirect',
    'resi_connection': '1conv',
}


class MambaIrV2LightRestorer:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies
        self._arch_module: Any | None = None
        self._models: dict[tuple[int, str], Any] = {}

    def available(self) -> bool:
        return all(
            dependency is not None
            for dependency in [
                self._dependencies.cv2,
                self._dependencies.einops,
                self._dependencies.numpy,
                self._dependencies.timm,
                self._dependencies.torch,
            ]
        )

    def restore(self, image: Any, scale: int = 2) -> Any:
        if image is None or getattr(image, 'size', 0) == 0 or not self.available():
            return None

        resolved_scale = 4 if int(scale) >= 4 else 2
        preferred_device = self._dependencies.preferred_torch_device()
        try:
            return self._infer(image, resolved_scale, preferred_device)
        except Exception:
            if preferred_device == 'cpu':
                raise
            return self._infer(image, resolved_scale, 'cpu')

    def _infer(self, image: Any, scale: int, device: str) -> Any:
        torch = self._dependencies.torch
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        model = self._load_model(scale, device)

        original_height, original_width = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        rgb = self._pad_for_windowing(rgb)
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).float().unsqueeze(0) / 255.0
        tensor = tensor.to(device)

        with torch.inference_mode():
            output = model(tensor).clamp_(0.0, 1.0)

        restored = output.squeeze(0).permute(1, 2, 0).detach().cpu().numpy()
        restored = numpy.clip((restored * 255.0) + 0.5, 0, 255).astype('uint8')
        restored = restored[: original_height * scale, : original_width * scale]
        return cv2.cvtColor(restored, cv2.COLOR_RGB2BGR)

    def _pad_for_windowing(self, image: Any) -> Any:
        cv2 = self._dependencies.cv2
        window_size = int(_LIGHT_CONFIG['window_size'])
        height, width = image.shape[:2]
        target_height = max(window_size, ((height + window_size - 1) // window_size) * window_size)
        target_width = max(window_size, ((width + window_size - 1) // window_size) * window_size)
        pad_bottom = target_height - height
        pad_right = target_width - width
        if pad_bottom == 0 and pad_right == 0:
            return image
        return cv2.copyMakeBorder(image, 0, pad_bottom, 0, pad_right, cv2.BORDER_REFLECT_101)

    def _load_model(self, scale: int, device: str) -> Any:
        cache_key = (scale, device)
        cached = self._models.get(cache_key)
        if cached is not None:
            return cached

        module = self._load_arch_module()
        model_type = getattr(module, 'MambaIRv2Light', None)
        if model_type is None:
            raise RuntimeFailure('Unable to resolve MambaIRv2Light from the downloaded architecture file.')

        torch = self._dependencies.torch
        model = model_type(upscale=scale, **_LIGHT_CONFIG)
        state_dict = self._extract_state_dict(torch.load(self._ensure_weights(scale), map_location='cpu'))
        model.load_state_dict(state_dict, strict=True)
        model.eval()
        model.to(device)
        self._models[cache_key] = model
        return model

    def _load_arch_module(self) -> Any:
        if self._arch_module is not None:
            return self._arch_module

        stubs_root = Path(__file__).resolve().parent / 'restoration' / 'stubs'
        if str(stubs_root) not in sys.path:
            sys.path.insert(0, str(stubs_root))

        arch_path = self._ensure_vendor_arch()
        spec = importlib.util.spec_from_file_location(_ARCH_MODULE_NAME, arch_path)
        if spec is None or spec.loader is None:
            raise RuntimeFailure(f'Unable to load the MambaIRv2Light architecture from {arch_path}.')

        module = importlib.util.module_from_spec(spec)
        sys.modules[_ARCH_MODULE_NAME] = module
        spec.loader.exec_module(module)
        self._arch_module = module
        return module

    def _ensure_vendor_arch(self) -> Path:
        vendor_dir = self._dependencies.vendor_cache_root() / 'mambair'
        vendor_dir.mkdir(parents=True, exist_ok=True)
        arch_path = vendor_dir / 'mambairv2light_arch.py'
        if arch_path.exists() and arch_path.stat().st_size > 0:
            return arch_path

        self._download_file(_ARCH_URL, arch_path)
        return arch_path

    def _ensure_weights(self, scale: int) -> Path:
        spec = _WEIGHT_SPECS[scale]
        weight_path = self._dependencies.models_root() / spec['filename']
        if weight_path.exists() and weight_path.stat().st_size > 0:
            return weight_path

        self._download_file(spec['url'], weight_path)
        return weight_path

    def _download_file(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_suffix(destination.suffix + '.tmp')
        try:
            with urllib.request.urlopen(url) as response, temp_path.open('wb') as handle:
                handle.write(response.read())
            temp_path.replace(destination)
        except Exception as error:
            temp_path.unlink(missing_ok=True)
            raise RuntimeFailure(f'Unable to download {url} to {destination}: {error}') from error

    def _extract_state_dict(self, checkpoint: Any) -> dict[str, Any]:
        if isinstance(checkpoint, dict):
            for key in ['params_ema', 'params', 'state_dict']:
                state_dict = checkpoint.get(key)
                if isinstance(state_dict, dict):
                    return self._strip_prefix(state_dict)
            if all(isinstance(name, str) for name in checkpoint.keys()):
                return self._strip_prefix(checkpoint)
        raise RuntimeFailure('Unexpected MambaIRv2 checkpoint format.')

    def _strip_prefix(self, state_dict: dict[str, Any]) -> dict[str, Any]:
        if not state_dict:
            return state_dict
        if not all(name.startswith('module.') for name in state_dict):
            return state_dict
        return {name.removeprefix('module.'): value for name, value in state_dict.items()}