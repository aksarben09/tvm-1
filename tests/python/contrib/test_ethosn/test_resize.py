# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Arm(R) Ethos(TM)-N integration resize tests"""

import pytest
import numpy as np
import tvm
from tvm import relay
from tvm.testing import requires_ethosn
from . import infrastructure as tei


def _get_model(
    shape,
    dtype,
    size,
    input_zp,
    input_sc,
    output_zp,
    output_sc,
    coordinate_transformation_mode,
    rounding_method,
):
    x = relay.var("x", shape=shape, dtype=dtype)
    resize = relay.image.resize2d(
        data=x,
        size=size,
        layout="NHWC",
        method="nearest_neighbor",
        coordinate_transformation_mode=coordinate_transformation_mode,
        rounding_method=rounding_method,
    )
    model = relay.qnn.op.requantize(
        resize,
        input_scale=relay.const(input_sc, "float32"),
        input_zero_point=relay.const(input_zp, "int32"),
        output_scale=relay.const(output_sc, "float32"),
        output_zero_point=relay.const(output_zp, "int32"),
        out_dtype=dtype,
    )
    return model


@requires_ethosn
@pytest.mark.parametrize("dtype", ["uint8", "int8"])
@pytest.mark.parametrize(
    "shape, size, coordinate_transformation_mode, rounding_method",
    [
        ((1, 4, 4, 2), (8, 8), "half_pixel", "round_prefer_ceil"),
        ((1, 4, 4, 2), (7, 7), "asymmetric", "floor"),
        ((1, 4, 8, 3), (8, 16), "half_pixel", "round_prefer_ceil"),
        ((1, 4, 8, 3), (7, 15), "asymmetric", "floor"),
    ],
)
def test_resize(dtype, shape, size, coordinate_transformation_mode, rounding_method):
    """Compare Resize output with TVM."""

    np.random.seed(0)
    zp_min = np.iinfo(dtype).min
    zp_max = np.iinfo(dtype).max
    inputs = {
        "x": tvm.nd.array(np.random.randint(zp_min, high=zp_max + 1, size=shape, dtype=dtype)),
    }
    outputs = []
    for npu in [False, True]:
        model = _get_model(
            shape=shape,
            dtype=dtype,
            size=size,
            input_zp=zp_min + 128,
            input_sc=0.0784314,
            output_zp=zp_min + 128,
            output_sc=0.0784314,
            coordinate_transformation_mode=coordinate_transformation_mode,
            rounding_method=rounding_method,
        )
        mod = tei.make_module(model, {})
        x = tei.build_and_run(mod, inputs, 1, {}, npu=npu)
        outputs.append(x)

    tei.verify(outputs, dtype, 1)


@requires_ethosn
def test_resize_failure():
    """Check Resize error messages."""

    trials = [
        (
            (30, 20),
            "Requested height isn't supported",
        ),
        (
            (20, 30),
            "Requested width isn't supported",
        ),
        (
            (19, 20),
            "Requested width and height must be both even or both odd",
        ),
        (
            (20, 19),
            "Requested width and height must be both even or both odd",
        ),
    ]
    dtype = "int8"
    zp_min = np.iinfo(dtype).min

    for size, err_msg in trials:
        model = _get_model(
            shape=(1, 10, 10, 1),
            dtype=dtype,
            size=size,
            input_zp=zp_min + 128,
            input_sc=0.0784314,
            output_zp=zp_min + 128,
            output_sc=0.0784314,
            coordinate_transformation_mode="half_pixel",
            rounding_method="round_prefer_ceil",
        )
        model = tei.make_ethosn_composite(model, "ethos-n.qnn_resize")
        mod = tei.make_ethosn_partition(model)
        tei.test_error(mod, {}, err_msg)
