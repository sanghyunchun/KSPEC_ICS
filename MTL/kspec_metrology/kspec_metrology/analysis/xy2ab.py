





def _find_angle_double_method2_ccw(
    ori_x, ori_y,
    target_x_ori, target_y_ori,
    elbow="down",
):
    """
    (내부용) 반시계방향(CCW) 정의에서 elbow 선택 버전
    elbow="down": phi in [0, +pi]
    elbow="up"  : phi in [-pi, 0]
    반환: theta, phi (rad), theta는 [0,2pi)
    """
    arm1 = 5.13
    arm2 = 11.43
    Positioner_p = arm1 + arm2

    elbow = str(elbow).lower()
    if elbow not in ("down", "up"):
        raise ValueError("elbow must be 'down' or 'up'")
    sgn = +1.0 if elbow == "down" else -1.0

    # base 기준 상대좌표
    target_x = target_x_ori - ori_x
    target_y = target_y_ori - ori_y

    d = float(np.hypot(target_x, target_y))
    gamma = float(np.arctan2(target_y, target_x))  # [-pi, pi]

    # ---- 도달 불가능: 너무 멀면 완전 펼침(phi=0) ----
    if d >= Positioner_p:
        theta = gamma
        phi = 0.0

    # ---- 도달 불가능: 너무 가까우면 완전 접힘(phi=±pi) ----
    elif d <= abs(arm2 - arm1):
        theta = gamma + np.pi
        phi = (np.pi if sgn > 0 else -np.pi)

    # ---- 도달 가능: elbow 선택 ----
    else:
        arg = (d**2 - arm1**2 - arm2**2) / (-2.0 * arm1 * arm2)
        arg = float(np.clip(arg, -1.0, 1.0))

        theta_beta = float(np.arccos(arg))
        phi_mag = float(np.pi - theta_beta)  # (0~pi)
        phi = sgn * phi_mag                  # down:+, up:-

        theta_alpha = float(np.arctan2(
            arm2 * np.sin(phi),
            arm1 + arm2 * np.cos(phi)
        ))
        theta = float(gamma - theta_alpha)

    # ---- theta를 항상 [0, 2pi)로 정규화 ----
    theta = float(theta % (2.0 * np.pi))

    # ---- phi 범위 정리 ----
    if sgn > 0:
        phi = float(np.clip(phi, 0.0, np.pi))       # down
    else:
        phi = float(np.clip(phi, -np.pi, 0.0))      # up

    return theta, phi


def find_angle_double_method2_select_elbow(
    ori_x, ori_y,
    target_x_ori, target_y_ori,
    elbow="down",
    clockwise=False,
):
    """

    elbow="down"/"up" 선택 가능
    clockwise=False : 반시계(CCW) 정의 (기존과 동일)
    clockwise=True  : 시계(CW) 정의 (각도 증가가 시계방향)

    반환: theta, phi (rad)
      - theta는 항상 [0, 2pi)
      - elbow-down이면 phi는 [0, pi], elbow-up이면 [-pi, 0]
        (clockwise=True에서도 동일하게 유지되도록 자동 변환)
    """
    elbow = str(elbow).lower()
    if elbow not in ("down", "up"):
        raise ValueError("elbow must be 'down' or 'up'")

    if not clockwise:
        # 기존(반시계) 그대로
        return _find_angle_double_method2_ccw(
            ori_x, ori_y, target_x_ori, target_y_ori, elbow=elbow
        )

    # --- 시계방향(CW) 각도 정의 ---
    # CW로 바꾸면 (theta, phi)를 단순히 부호반전하면 되는데,
    # elbow-down/up의 phi 부호 조건을 유지하려면 elbow를 swap해서 계산해야 함.
    elbow_ccw = ("up" if elbow == "down" else "down")

    theta_ccw, phi_ccw = _find_angle_double_method2_ccw(
        ori_x, ori_y, target_x_ori, target_y_ori, elbow=elbow_ccw
    )

    theta = float((-theta_ccw) % (2.0 * np.pi))
    phi   = float(-phi_ccw)

    # phi 범위 강제 (수치오차 방지)
    if elbow == "down":
        phi = float(np.clip(phi, 0.0, np.pi))
    else:
        phi = float(np.clip(phi, -np.pi, 0.0))

    return theta, phi
