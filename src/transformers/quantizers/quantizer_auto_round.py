# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import importlib
from typing import TYPE_CHECKING, Optional

from packaging import version

from .base import HfQuantizer


if TYPE_CHECKING:
    from ..modeling_utils import PreTrainedModel

from ..utils import is_auto_round_available, is_optimum_available, is_torch_available, logging
from ..utils.quantization_config import QuantizationConfigMixin


if is_torch_available():
    import torch

logger = logging.get_logger(__name__)


class AutoRoundQuantizer(HfQuantizer):
    """
    Quantizer of the AutoRound method. (https://arxiv.org/pdf/2309.05516)
    """

    requires_calibration = False
    required_packages = ["optimum", "auto_round"]
    optimum_quantizer = None

    def __init__(self, quantization_config: QuantizationConfigMixin, **kwargs):
        super().__init__(quantization_config, **kwargs)

    def validate_environment(self, *args, **kwargs):
        self.device_map = kwargs.get("device_map", None)
        if not is_auto_round_available():
            raise ImportError(
                "Loading an AutoRound quantized model requires auto-round library (`pip install 'auto-round>=0.5'`)"
            )

        autoround_version = version.parse(importlib.metadata.version("auto_round"))
        if autoround_version < version.parse("0.5.0"):
            raise ImportError(
                "You need a version of auto_round >= 0.5.0 to use AutoRound: `pip install --upgrade auto-round`"
            )

        if not is_optimum_available():
            raise ImportError("Loading a AutoRound quantized model requires optimum (`pip install optimum`)")

        ## In AutoRound, we offer on-demand reminders to install necessary packages, such as IPEX.

    def update_torch_dtype(self, torch_dtype: "torch.dtype") -> "torch.dtype":
        if torch_dtype is None:
            torch_dtype = torch.float16
            logger.info("Loading the model in `torch.float16`. To overwrite it, set `torch_dtype` manually.")
        elif torch_dtype != torch.float16:
            logger.info("We suggest you to set `torch_dtype=torch.float16` for better efficiency with AutoRound")
        return torch_dtype

    def _process_model_before_weight_loading(self, model: "PreTrainedModel", **kwargs):
        if model.__class__.main_input_name != "input_ids":
            logger.warning("We provide limited support for models that are not purely text-based.")
        from auto_round.inference.convert_model import convert_hf_model, infer_target_device

        if self.pre_quantized:
            target_device = infer_target_device(self.device_map)
            model, used_backends = convert_hf_model(model, target_device)
            self.used_backends = used_backends

    def _process_model_after_weight_loading(self, model: "PreTrainedModel", **kwargs):
        if self.pre_quantized:
            from auto_round.inference.convert_model import post_init

            post_init(model, self.used_backends)
        else:
            raise NotImplementedError

    @property
    def is_trainable(self, model: Optional["PreTrainedModel"] = None):
        return True

    def is_serializable(self, safe_serialization=None):
        return True
