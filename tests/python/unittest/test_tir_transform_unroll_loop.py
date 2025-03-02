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
import tvm
from tvm import te
from tvm.script import tir as T
import os


def test_unroll_loop():
    ib = tvm.tir.ir_builder.create()
    dtype = "int64"
    n = te.size_var("n")
    Ab = tvm.tir.decl_buffer((n,), dtype)
    Aptr = ib.buffer_ptr(Ab)
    # for i in 0 to n-1:
    with ib.for_range(n, n + 2, name="i") as i:
        with ib.for_range(0, 8, name="i", kind="unroll") as j:
            Aptr[j + 1] = Aptr[i] + 1

    stmt = ib.get()
    mod = tvm.IRModule.from_expr(tvm.tir.PrimFunc([Ab], stmt))

    assert isinstance(stmt, tvm.tir.For)

    with tvm.transform.PassContext(config={"tir.UnrollLoop": {"auto_max_step": 16}}):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert not isinstance(ret, tvm.tir.For)

    with tvm.transform.PassContext(config={"tir.UnrollLoop": {"auto_max_step": 15}}):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert isinstance(ret, tvm.tir.For)

    with tvm.transform.PassContext(
        config={"tir.UnrollLoop": {"auto_max_step": 16, "explicit_unroll": False}}
    ):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert isinstance(ret, tvm.tir.For)
        assert ret.kind == tvm.tir.ForKind.UNROLLED

    ib = tvm.tir.ir_builder.create()
    ib.scope_attr(tvm.tir.const(0, "int32"), "pragma_auto_unroll_max_step", 16)
    ib.emit(stmt)
    wrapped = ib.get()
    wrapped = tvm.tir.SeqStmt([wrapped, stmt])
    assert isinstance(ret, tvm.tir.For)
    mod = tvm.IRModule.from_expr(tvm.tir.PrimFunc([Ab], wrapped))

    with tvm.transform.PassContext(
        config={"tir.UnrollLoop": {"auto_max_depth": 8, "explicit_unroll": False}}
    ):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert isinstance(ret[0], tvm.tir.For)
        assert ret[0].kind == tvm.tir.ForKind.UNROLLED
        assert isinstance(ret[1], tvm.tir.For)
        assert ret[1].kind != tvm.tir.ForKind.UNROLLED


def test_unroll_fake_loop():
    ib = tvm.tir.ir_builder.create()
    dtype = "int32"
    n = te.size_var("n")
    Ab = tvm.tir.decl_buffer((n,), dtype)
    Aptr = ib.buffer_ptr(Ab)
    # for i in 0 to n-1:
    with ib.for_range(0, 1, name="i") as i:
        Aptr[i * 2] = 3
        with ib.for_range(0, 10, name="j") as j:
            Aptr[j + 1] = Aptr[i] + 1

    stmt = ib.get()

    mod = tvm.IRModule.from_expr(tvm.tir.PrimFunc([Ab], stmt))

    with tvm.transform.PassContext(
        config={
            "tir.UnrollLoop": {"auto_max_depth": 8, "auto_max_extent": 1, "explicit_unroll": False}
        }
    ):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert isinstance(ret[0], tvm.tir.BufferStore)


def test_unroll_single_count_loops():
    n = te.size_var("n")
    A = te.placeholder((n,), name="A")
    B = te.compute((n,), lambda *i: A(*i), name="B")
    s = te.create_schedule(B.op)
    s = s.normalize()
    dom_map = tvm.te.schedule.InferBound(s)
    stmt = tvm.te.schedule.ScheduleOps(s, dom_map)
    # all parameters to UnrolLoops are default values except for
    # auto_unroll_max_extent which has been set to 1 (default:0)
    mod = tvm.IRModule.from_expr(tvm.tir.PrimFunc([], stmt))

    with tvm.transform.PassContext(config={"tir.UnrollLoop": {"auto_max_step": 1}}):
        ret = tvm.tir.transform.UnrollLoop()(mod)["main"].body
        assert ret == stmt


def test_unroll_allocations():
    @tvm.script.ir_module
    class before:
        @T.prim_func
        def main():
            for i in T.unroll(2):
                with T.allocate([16], "float32", "global") as buf_data:
                    buf = T.buffer_decl(shape=[16], dtype="float32", data=buf_data)
                    buf[0] = 0.0

    @tvm.script.ir_module
    class expected:
        @T.prim_func
        def main():
            with T.allocate([16], "float32", "global") as buf1_data:
                buf1 = T.buffer_decl(shape=[16], dtype="float32", data=buf1_data)
                buf1[0] = 0.0
            with T.allocate([16], "float32", "global") as buf2_data:
                buf2 = T.buffer_decl(shape=[16], dtype="float32", data=buf2_data)
                buf2[0] = 0.0

    after = tvm.tir.transform.UnrollLoop()(before)

    tvm.ir.assert_structural_equal(after, expected)


if __name__ == "__main__":
    test_unroll_loop()
    test_unroll_fake_loop()
    test_unroll_single_count_loops()
    test_unroll_allocations()
