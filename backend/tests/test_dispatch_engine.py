import pytest

from app.services.dispatch_engine import (
    DISTANCE_WEIGHT,
    IDLE_BONUS,
    SAME_DIR_BONUS,
    CallRequest,
    CarState,
    pick_car,
    score_car,
)


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
# 表驱动派梯用例
#
# 金样 = 当前引擎语义，不改动引擎来迎合本表：
#   基础分 100 - DISTANCE_WEIGHT * 距离（权重 5）
#   idle 加 IDLE_BONUS(20)；同向且未过站加 SAME_DIR_BONUS(40)；同向但已过站扣 15；反向扣 25
#   pick_car 用内置 max 取最高分，平局时返回输入列表中第一台（现网 max 行为）
#
# 每行字段：
#   name    用例名（pytest 用例 id，失败时直接可见）
#   summary 轿厢列表摘要（轿厢号/当前层/方向/载重）
#   call    呼梯：候梯层、方向、人数（CallRequest(call_id, floor, direction, passengers)）
#   expect  期望胜者轿厢号；全部不可接时为 "reject"
#   reason  expect == "reject" 或存在 also_rejected 时，断言拒绝原因包含该串
#   note    边界说明；标注“现网行为”表示该边界与引擎注释字面不一致，以代码实际行为准
# ---------------------------------------------------------------------------
TABLE_CASES = [
    {
        "name": "01_load_plus_passengers_over_capacity_rejected",
        "summary": "1号梯 5层 idle 载重8/8",
        "cars": [CarState(1, 5, "idle", load=8, capacity=8)],
        "call": CallRequest(1, floor=5, direction="up", passengers=1),
        "expect": "reject",
        "reason": "轿厢满员",
        "note": "载荷8+呼梯人数1=9 > 容量8，超容量满员拒绝；pick_car 无车可接返回 None",
    },
    {
        "name": "02_exactly_full_still_accepted_current_behavior",
        "summary": "1号梯 5层 idle 载重9/10",
        "cars": [CarState(1, 5, "idle", load=9, capacity=10)],
        "call": CallRequest(2, floor=5, direction="up", passengers=1),
        "expect": 1,
        "note": (
            "现网行为：载荷9+人数1=10 == 容量10（恰好满载）仍被接单——引擎拒载条件是 "
            "load+passengers > capacity（严格大于），并非文件头注释所说的 “reject if car full”。"
            "本行以代码实际边界（> 而非 >=）为准，不改引擎。"
        ),
    },
    {
        "name": "03_same_direction_approaching_beats_opposite",
        "summary": "1号梯 6层 up 载重0/10；2号梯 4层 down 载重0/10",
        "cars": [
            CarState(1, 6, "up", load=0, capacity=10),
            CarState(2, 4, "down", load=0, capacity=10),
        ],
        "call": CallRequest(3, floor=8, direction="up", passengers=1),
        "expect": 1,
        "note": (
            "候梯8层向上。1号梯同向未过站：100-2*5+40=130；"
            "2号梯反向：100-4*5-25=55。同向未过站加分高于反向。"
        ),
    },
    {
        "name": "04_same_direction_down_approaching_beats_opposite",
        "summary": "1号梯 10层 down 载重0/10；2号梯 2层 up 载重0/10",
        "cars": [
            CarState(1, 10, "down", load=0, capacity=10),
            CarState(2, 2, "up", load=0, capacity=10),
        ],
        "call": CallRequest(4, floor=6, direction="down", passengers=2),
        "expect": 1,
        "note": (
            "候梯6层向下、2人。1号梯下行且当前层10>=6（未过站）：100-4*5+40=120；"
            "2号梯反向：100-4*5-25=55。下行方向对称覆盖。"
        ),
    },
    {
        "name": "05_same_direction_already_passed_loses_to_farther_idle",
        "summary": "1号梯 8层 up 载重0/10；2号梯 10层 idle 载重0/10",
        "cars": [
            CarState(1, 8, "up", load=0, capacity=10),
            CarState(2, 10, "idle", load=0, capacity=10),
        ],
        "call": CallRequest(5, floor=3, direction="up", passengers=1),
        "expect": 2,
        "note": (
            "候梯3层向上。1号梯虽同向但已越过候梯层（8>3），扣15：100-5*5-15=60；"
            "2号梯距离更远（7层）但空闲+20：100-7*5+20=85。已过站扣分后负于更远的空闲车。"
        ),
    },
    {
        "name": "06_idle_bonus_and_distance_jointly_decide_winner",
        "summary": "1号梯 4层 down 载重0/10；2号梯 12层 idle 载重0/10",
        "cars": [
            CarState(1, 4, "down", load=0, capacity=10),
            CarState(2, 12, "idle", load=0, capacity=10),
        ],
        "call": CallRequest(6, floor=5, direction="up", passengers=1),
        "expect": 2,
        "note": (
            "候梯5层向上。1号梯仅距1层但反向：100-1*5-25=70；"
            "2号梯距7层，空闲加分后：100-7*5+20=85。"
            "若没有空闲加分，2号梯只有65分反而落败——空闲加分与距离权重共同决定胜者。"
        ),
    },
    {
        "name": "07_distance_weight_breaks_idle_vs_idle",
        "summary": "1号梯 4层 idle 载重0/10；2号梯 9层 idle 载重0/10",
        "cars": [
            CarState(1, 4, "idle", load=0, capacity=10),
            CarState(2, 9, "idle", load=0, capacity=10),
        ],
        "call": CallRequest(7, floor=5, direction="up", passengers=1),
        "expect": 1,
        "note": (
            "两台均空闲、加分相同，距离权重决定：1号梯 100-1*5+20=115，"
            "2号梯 100-4*5+20=100，近者胜。"
        ),
    },
    {
        "name": "08_equal_scores_max_keeps_first_in_list",
        "summary": "1号梯 5层 idle 载重0/10；2号梯 1层 up 载重0/10",
        "cars": [
            CarState(1, 5, "idle", load=0, capacity=10),
            CarState(2, 1, "up", load=0, capacity=10),
        ],
        "call": CallRequest(8, floor=5, direction="up", passengers=1),
        "expect": 1,
        "note": (
            "现网行为：两台均可接且同分——1号梯 100-0+20=120，"
            "2号梯同向未过站 100-4*5+40=120。pick_car 用内置 max，"
            "平局稳定返回输入列表中第一台，即1号梯。"
        ),
    },
    {
        "name": "09_equal_scores_max_keeps_first_after_order_swap",
        "summary": "2号梯 1层 up 载重0/10；1号梯 5层 idle 载重0/10（列表顺序调换）",
        "cars": [
            CarState(2, 1, "up", load=0, capacity=10),
            CarState(1, 5, "idle", load=0, capacity=10),
        ],
        "call": CallRequest(9, floor=5, direction="up", passengers=1),
        "expect": 2,
        "note": (
            "现网行为：与上一行同一场景、同分120，仅调换输入顺序；max 仍取列表第一台，"
            "因此胜者随之变为排在最前的2号梯。以输入顺序稳定断言现网平局行为。"
        ),
    },
    {
        "name": "10_full_car_filtered_other_car_accepts",
        "summary": "1号梯 2层 idle 载重10/10；2号梯 9层 idle 载重0/10",
        "cars": [
            CarState(1, 2, "idle", load=10, capacity=10),
            CarState(2, 9, "idle", load=0, capacity=10),
        ],
        "call": CallRequest(10, floor=5, direction="up", passengers=1),
        "expect": 2,
        "reason": "轿厢满员",
        "also_rejected": [1],
        "note": "1号梯超容量被过滤（原因“轿厢满员”），2号梯 100-4*5+20=100 接单。",
    },
    {
        "name": "11_all_cars_full_pick_returns_none",
        "summary": "1号梯 3层 up 载重10/10；2号梯 7层 down 载重9/10",
        "cars": [
            CarState(1, 3, "up", load=10, capacity=10),
            CarState(2, 7, "down", load=9, capacity=10),
        ],
        "call": CallRequest(11, floor=5, direction="up", passengers=2),
        "expect": "reject",
        "reason": "轿厢满员",
        "note": "1号梯10+2>10、2号梯9+2>10，两台均超容量拒绝，pick_car 返回 None。",
    },
]


@pytest.mark.parametrize(
    "row,case",
    [pytest.param(i, c, id=c["name"]) for i, c in enumerate(TABLE_CASES, start=1)],
)
def test_dispatch_table(row, case):
    call = case["call"]
    results = [score_car(car, call) for car in case["cars"]]
    by_id = {r.car_id: r for r in results}
    score_detail = ", ".join(
        f"车{r.car_id}={r.score:g}({'ok' if r.accepted else r.reason})" for r in results
    )
    label = f"第{row}行[{case['name']}]"

    if case["expect"] == "reject":
        assert all(not r.accepted for r in results), (
            f"{label} 期望全部拒绝，实际存在可接轿厢：{score_detail}"
        )
        for r in results:
            assert case["reason"] in r.reason, (
                f"{label} 车{r.car_id} 拒绝原因期望包含 {case['reason']!r}，实际 {r.reason!r}"
            )
        assert pick_car(case["cars"], call) is None, (
            f"{label} 全部超容量时 pick_car 应返回 None，实际仍选出了轿厢"
        )
        return

    for car_id in case.get("also_rejected", []):
        r = by_id[car_id]
        assert r.accepted is False, f"{label} 车{car_id} 期望被拒绝，实际接单：{score_detail}"
        assert case["reason"] in r.reason, (
            f"{label} 车{car_id} 拒绝原因期望包含 {case['reason']!r}，实际 {r.reason!r}"
        )

    best = pick_car(case["cars"], call)
    assert best is not None, f"{label} 期望车{case['expect']}接单，但全部被拒：{score_detail}"
    assert best.car_id == case["expect"], (
        f"{label} 期望胜者车{case['expect']}，实际车{best.car_id}；分数明细：{score_detail}"
    )
