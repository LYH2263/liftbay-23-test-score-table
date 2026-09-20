from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.dispatch_engine import CallRequest, CarState, pick_car, score_car


def test_reject_when_full():
    car = CarState(1, 5, "idle", load=8, capacity=8)
    call = CallRequest(1, 5, "up", passengers=1)
    r = score_car(car, call)
    assert r.accepted is False
    assert "满员" in r.reason


def test_same_direction_beats_far_idle():
    cars = [
        CarState(1, 2, "up", load=1, capacity=10),
        CarState(2, 12, "idle", load=0, capacity=10),
    ]
    call = CallRequest(9, 4, "up", 1)
    best = pick_car(cars, call)
    assert best is not None
    assert best.car_id == 1


def test_closer_idle_wins_when_opposite():
    cars = [
        CarState(1, 10, "down", load=0, capacity=10),
        CarState(2, 3, "idle", load=0, capacity=10),
    ]
    call = CallRequest(3, 2, "up", 1)
    best = pick_car(cars, call)
    assert best is not None
    assert best.car_id == 2


# ---------------------------------------------------------------------------
# 表驱动测例（以当前引擎语义为金样，不为迎合断言而改引擎）
#
# 评分规则快照（app/services/dispatch_engine.py）：
#   base = 100 - 5 * |轿厢层 - 呼梯层|
#   idle +20；同向未过站 +40；同向已过站 -15；反向 -25
#   load + passengers > capacity → 拒绝（reason 含 "轿厢满员"，score=-1e9）
#   pick_car 用内置 max()：平局时取列表中先出现者（现网行为，无显式 tie-break）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchCase:
    name: str
    cars: tuple[CarState, ...]          # 轿厢列表摘要：(id, 层, 方向, 载荷, 容量)
    call: CallRequest                   # 呼梯：候梯层 / 方向 / 人数
    expected_winner: int | None         # 期望胜者 car_id；None 表示全部拒绝
    expected_reason: str | None         # 拒绝原因关键字；胜者行填 None
    note: str = ""                      # 分数演算 / 现网行为标注
    expect_tie: bool = False            # True 时断言所有可接轿厢同分


def C(car_id, floor, direction, load=0, capacity=10):
    """构造轿厢的简写，让表行保持紧凑。"""
    return CarState(car_id, floor, direction, load, capacity)


DISPATCH_CASES: tuple[DispatchCase, ...] = (
    # --- 载荷 + 人数超容量 → 满员拒绝 ---
    DispatchCase(
        "full_car_rejects_single",
        cars=(C(1, 5, "idle", load=8, capacity=8),),
        call=CallRequest(1, 5, "up", passengers=1),
        expected_winner=None, expected_reason="满员",
        note="8+1 > 8 → 拒绝"),
    DispatchCase(
        "full_car_rejects_multi_passengers",
        cars=(C(1, 5, "idle", load=6, capacity=8),),
        call=CallRequest(1, 5, "up", passengers=3),
        expected_winner=None, expected_reason="满员",
        note="6+3 > 8 → 拒绝（按人数累计，不是按呼叫次数）"),
    DispatchCase(
        "all_cars_full_pick_returns_none",
        cars=(C(1, 5, "idle", load=8, capacity=8),
              C(2, 3, "up", load=10, capacity=10)),
        call=CallRequest(1, 5, "up", passengers=1),
        expected_winner=None, expected_reason="满员",
        note="两台都满 → pick_car 返回 None"),
    DispatchCase(
        "exact_full_load_accepted",
        cars=(C(1, 5, "idle", load=7, capacity=8),),
        call=CallRequest(1, 5, "up", passengers=1),
        expected_winner=1, expected_reason=None,
        note="边界：7+1 == 8 恰好满载仍接受（严格大于才拒绝）；score=100-0+20=120"),

    # --- 同向未过站加分 > 反向 ---
    DispatchCase(
        "same_dir_approaching_beats_opposite_at_call_floor",
        cars=(C(1, 2, "up"), C(2, 5, "down")),
        call=CallRequest(1, 5, "up", 1),
        expected_winner=1, expected_reason=None,
        note="car1 同向未过站 100-15+40=125 > car2 反向（虽就在呼梯层）100-0-25=75"),
    DispatchCase(
        "same_dir_down_approaching_beats_opposite",
        cars=(C(1, 10, "down"), C(2, 8, "up")),
        call=CallRequest(1, 8, "down", 1),
        expected_winner=1, expected_reason=None,
        note="下行镜像：car1 100-10+40=130 > car2 反向 100-0-25=75"),

    # --- 同向已过站扣分后 < 更远空闲车 ---
    DispatchCase(
        "same_dir_passed_loses_to_farther_idle",
        cars=(C(1, 5, "up"), C(2, 8, "idle")),
        call=CallRequest(1, 3, "up", 1),
        expected_winner=2, expected_reason=None,
        note="car1 同向已过站 100-10-15=75 < car2 更远空闲 100-25+20=95"),

    # --- 空闲加分与距离权重共同决定胜者 ---
    DispatchCase(
        "nearer_idle_wins_on_distance",
        cars=(C(1, 2, "idle"), C(2, 9, "idle")),
        call=CallRequest(1, 5, "up", 1),
        expected_winner=1, expected_reason=None,
        note="同享空闲加分，距离权重定胜负：100-15+20=105 > 100-20+20=100"),
    DispatchCase(
        "idle_at_call_floor_beats_far_same_dir",
        cars=(C(1, 6, "idle"), C(2, 1, "up")),
        call=CallRequest(1, 6, "up", 1),
        expected_winner=1, expected_reason=None,
        note="空闲+零距离 100-0+20=120 > 同向未过站但距5层 100-25+40=115"),

    # --- 两台均可接且同分 → 平局（现网 max 行为） ---
    DispatchCase(
        "tie_first_listed_car_wins",
        cars=(C(1, 4, "idle"), C(2, 4, "idle")),
        call=CallRequest(1, 6, "up", 1),
        expected_winner=1, expected_reason=None, expect_tie=True,
        note="现网行为：两车同分 110，max() 取列表先出现者"),
    DispatchCase(
        "tie_swapped_order_flips_winner",
        cars=(C(2, 4, "idle"), C(1, 4, "idle")),
        call=CallRequest(1, 6, "up", 1),
        expected_winner=2, expected_reason=None, expect_tie=True,
        note="现网行为：交换列表顺序后胜者随之翻转，证明平局靠位置而非 car_id"),
)


@pytest.mark.parametrize(
    "case",
    DISPATCH_CASES,
    ids=[f"{i:02d}_{c.name}" for i, c in enumerate(DISPATCH_CASES, 1)],
)
def test_dispatch_table(case: DispatchCase):
    results = [score_car(c, case.call) for c in case.cars]

    if case.expected_winner is None:
        # 全部拒绝：逐台断言拒绝原因，且 pick_car 返回 None
        assert all(not r.accepted for r in results), case.name
        for r in results:
            assert case.expected_reason in r.reason, case.name
        assert pick_car(list(case.cars), case.call) is None, case.name
        return

    if case.expect_tie:
        scores = [r.score for r in results if r.accepted]
        assert len(scores) == len(case.cars) and len(set(scores)) == 1, case.name

    best = pick_car(list(case.cars), case.call)
    assert best is not None, case.name
    assert best.accepted, case.name
    assert best.car_id == case.expected_winner, (
        f"{case.name}: 期望 car {case.expected_winner}，实际 car {best.car_id}"
        f"（{case.note}）"
    )
