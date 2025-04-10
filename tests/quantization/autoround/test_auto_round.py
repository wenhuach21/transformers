# Copyright 2025 The HuggingFace Team. All rights reserved.
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
import gc
import tempfile
import unittest

from transformers import AutoModelForCausalLM, AutoRoundConfig, AutoTokenizer
from transformers.testing_utils import (
    require_accelerate,
    require_auto_round,
    require_intel_extension_for_pytorch,
    require_torch_gpu,
    require_torch_multi_gpu,
    slow,
    torch_device,
)
from transformers.utils import is_torch_available

if is_torch_available():
    import torch


@slow
@require_torch_gpu
@require_auto_round
@require_accelerate
class AutoRoundTest(unittest.TestCase):
    model_name = "OPEA/Qwen2.5-1.5B-Instruct-int4-sym-inc"
    input_text = "There is a girl who likes adventure,"

    EXPECTED_OUTPUT = ('There is a girl who likes adventure, and she has been exploring the world '
                       'for many years. She travels to different countries and cultures, trying new '
                       'things every day. One of her favorite places to visit is a small village in '
                       'the mountains where')

    device_map = "cuda"

    # called only once for all test in this class
    @classmethod
    def setUpClass(cls):
        """
        Setup quantized model
        """
        torch.cuda.synchronize()
        cls.tokenizer = AutoTokenizer.from_pretrained(cls.model_name)
        cls.quantized_model = AutoModelForCausalLM.from_pretrained(
            cls.model_name, device_map=cls.device_map, torch_dtype=torch.float16
        )

    def tearDown(self):
        gc.collect()
        torch.cuda.empty_cache()
        gc.collect()

    def test_quantized_model(self):
        """
        Simple test that checks if the quantized model is working properly
        """
        input_ids = self.tokenizer(self.input_text, return_tensors="pt").to(torch_device)
        output = self.quantized_model.generate(**input_ids, max_new_tokens=40, do_sample=False)
        self.assertEqual(self.tokenizer.decode(output[0], skip_special_tokens=True), self.EXPECTED_OUTPUT)

    def test_raise_if_non_quantized(self):
        model_id = "facebook/opt-125m"
        quantization_config = AutoRoundConfig(bits=4)
        with self.assertRaises(NotImplementedError):
            _ = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=quantization_config)

    def test_quantized_model_bf16(self):
        """
        Simple test that checks if the quantized model is working properly with bf16
        """
        input_ids = self.tokenizer(self.input_text, return_tensors="pt").to(torch_device)

        quantized_model = AutoModelForCausalLM.from_pretrained(self.model_name, torch_dtype=torch.bfloat16,
                                                               device_map="cuda")

        output = quantized_model.generate(**input_ids, max_new_tokens=40, do_sample=False)
        self.assertEqual(self.tokenizer.decode(output[0], skip_special_tokens=True), self.EXPECTED_OUTPUT)

    @require_intel_extension_for_pytorch
    def test_quantized_model_on_cpu(self):
        """
        Simple test that checks if the quantized model is working properly
        """
        input_ids = self.tokenizer(self.input_text, return_tensors="pt").to(torch_device)

        quantized_model = AutoModelForCausalLM.from_pretrained(self.model_name).to(torch_device)
        output = quantized_model.generate(**input_ids, max_new_tokens=40, do_sample=False)

        self.assertEqual(self.tokenizer.decode(output[0], skip_special_tokens=True), self.EXPECTED_OUTPUT)

    def test_save_pretrained(self):
        """
        Simple test that checks if the quantized model is working properly after being saved and loaded
        """
        with tempfile.TemporaryDirectory() as tmpdirname:
            self.quantized_model.save_pretrained(tmpdirname)
            model = AutoModelForCausalLM.from_pretrained(tmpdirname, device_map=self.device_map)

            input_ids = self.tokenizer(self.input_text, return_tensors="pt").to(torch_device)

            output = model.generate(**input_ids, max_new_tokens=40, do_sample=False)
            self.assertEqual(self.tokenizer.decode(output[0], skip_special_tokens=True), self.EXPECTED_OUTPUT)

    #
    @require_torch_multi_gpu
    def test_quantized_model_multi_gpu(self):
        """
        Simple test that checks if the quantized model is working properly with multiple GPUs
        """
        input_ids = self.tokenizer(self.input_text, return_tensors="pt").to(torch_device)

        quantized_model = AutoModelForCausalLM.from_pretrained(self.model_name, device_map="auto")

        output = quantized_model.generate(**input_ids, max_new_tokens=40, do_sample=False)

        self.assertEqual(self.tokenizer.decode(output[0], skip_special_tokens=True), self.EXPECTED_OUTPUT)

    def test_force_from_gptq(self):
        """
        Simple test that checks if auto-round work properly wth gptq format
        """
        model_name = "ybelkada/opt-125m-gptq-4bit"
        from transformers import AutoRoundConfig
        quantization_config = AutoRoundConfig()

        model = AutoModelForCausalLM.from_pretrained(model_name,
                                                     device_map="auto", quantization_config=quantization_config)
        tokenizer = AutoTokenizer.from_pretrained(model_name)

        text = "There is a girl who likes adventure,"
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        print(tokenizer.decode(model.generate(**inputs, max_new_tokens=5)[0]))

    def test_mixed_bits(self):
        """
        Simple test that checks if auto-round work properly wth mixed bits
        """
        model_name = "facebook/opt-125m"
        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", trust_remote_code=True)
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        layer_config = {"model.decoder.layers.0.self_attn.k_proj": {"bits": 8},
                        "model.decoder.layers.6.self_attn.out_proj": {"bits": 2, "group_size": 32}}

        bits, group_size, sym = 4, 128, True
        from auto_round import AutoRound
        autoround = AutoRound(
            model,
            tokenizer,
            bits=bits,
            group_size=group_size,
            sym=sym,
            layer_config=layer_config
        )
        with tempfile.TemporaryDirectory() as tmpdirname:
            autoround.quantize_and_save(output_dir=tmpdirname)
            model = AutoModelForCausalLM.from_pretrained(
                tmpdirname,
                torch_dtype=torch.float16,
                device_map="auto"
            )
        text = "There is a girl who likes adventure,"
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        print(tokenizer.decode(model.generate(**inputs, max_new_tokens=5)[0]))
