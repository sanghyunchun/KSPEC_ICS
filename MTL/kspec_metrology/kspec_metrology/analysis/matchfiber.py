import numpy as np
from scipy.spatial import cKDTree
from kspec_metrology.analysis.utils import transform, camera2focal_coeff
from kspec_metrology.logging.log import get_logger

def matchfiber(x, y
               , xobs_raw, yobs_raw
               , nbuffer=20
               , theta_init=0.
               , xoff_init=0., yoff_init=0.
               , m_init=None
               , center=True):
    """관측된 peak과 설계 위치를 짝지어 준다.

    회전각을 grid search로 먼저 찾고, 그 각도에서 (x, y) offset을 다시 grid
    search한 뒤, 가장 가까운 peak을 고른다.

    theta_init, xoff_init, yoff_init
        camera -> focal 변환에 미리 넣어 둘 대략적인 값. 모르면 0으로 두면 되고,
        테스트 관측으로 값을 알게 되면 그때 넣어 주면 된다. 반환하는 theta_guess
        와 offset은 이 초기값을 포함한 값이다.

    m_init
        배율(magnification) 초기값. None이면 camera2focal_coeff의 값을 쓴다.
        이 탐색은 회전과 offset만 훑고 배율은 맞추지 않으므로, 배율이 크게
        틀리면 매칭이 어긋난다. 테스트 관측에서 배율을 알게 되면 넣어 주면 된다.

    center
        회전각을 찾기 전에 두 point set의 무게중심을 맞춘다. 회전 탐색은 두
        set이 대략 겹쳐 있다고 보고 최근접 거리의 합을 재기 때문에, offset이
        크게 남아 있으면 엉뚱한 각도를 고른다. 무게중심을 맞춰 두면 초기값이
        전부 0이어도 회전각을 제대로 찾는다. 예전 동작을 그대로 보려면 False.

    nbuffer
        쓰이지 않는다. 예전 구현에서 KD-tree 이웃 개수였고, 호출부 호환을 위해
        인자만 남겨 두었다.

    반환:
        imatch      : 설계 위치 i에 대응하는 관측 peak의 index
        theta_guess : 추정된 회전각
        (xoff, yoff): 추정된 offset. fitdistortion의 초기값으로 쓴다.
    """
    log = get_logger()

    coeff_temp = np.copy(camera2focal_coeff)
    coeff_temp[1] = theta_init
    coeff_temp[2] = xoff_init
    coeff_temp[3] = yoff_init
    if m_init is not None:
        coeff_temp[0] = m_init
    xobs, yobs = transform(xobs_raw, yobs_raw, coeff_temp)

    obs = np.column_stack((xobs, yobs))
    tgt = np.column_stack((x, y))

    obs_c = obs.mean(axis=0) if center else np.zeros(2)
    tgt_c = tgt.mean(axis=0) if center else np.zeros(2)

    obs = obs - obs_c
    tx, ty = (tgt - tgt_c).T

    # 거리는 회전/평행이동에 대해 대칭이므로, 관측점을 매번 옮겨 KD-tree를 새로
    # 만드는 대신 관측점 트리를 한 번만 만들고 설계 위치를 반대로 옮겨 질의한다.
    #   |R(t)*obs + off - x| = |obs - R(-t)*(x - off)|
    tree = cKDTree(obs)

    #---회전각 탐색-------------------------------------------------------------
    log.info("Finding field rotation angle")

    nhunt = 720
    theta_grid = np.linspace(0., 2.*np.pi, nhunt)
    cos_t = np.cos(theta_grid)[:, None]
    sin_t = np.sin(theta_grid)[:, None]

    dd, _ = tree.query(np.column_stack((( cos_t*tx + sin_t*ty).ravel(),
                                        (-sin_t*tx + cos_t*ty).ravel())), k=1, workers=-1)

    dd_sum = dd.reshape(nhunt, -1).sum(axis=1)
    theta_guess = theta_grid[dd_sum.argmin()]
    log.info(f"Estimated rotation angle: {theta_guess}")

    #---offset 탐색-------------------------------------------------------------
    cos_g, sin_g = np.cos(theta_guess), np.sin(theta_guess)

    ngrid = 81
    offset_grid = np.linspace(-20., 20., ngrid)

    # y 방향 offset 전체를 한 번에 질의한다 (x 방향으로만 반복)
    ygrid = ty[None, :] - offset_grid[:, None]
    dsum_temp = np.empty((ngrid, ngrid))
    for i in range(ngrid):
        xgrid = tx - offset_grid[i]

        dd, _ = tree.query(np.column_stack((( cos_g*xgrid[None, :] + sin_g*ygrid).ravel(),
                                            (-sin_g*xgrid[None, :] + cos_g*ygrid).ravel())),
                           k=1, workers=-1)

        dsum_temp[i] = dd.reshape(ngrid, -1).sum(axis=1)

    imin, jmin = np.unravel_index(dsum_temp.argmin(), dsum_temp.shape)
    log.info(f"Estimated offset : ({offset_grid[imin]}, {offset_grid[jmin]})")

    #---최종 매칭---------------------------------------------------------------
    xgrid = tx - offset_grid[imin]
    ygrid = ty - offset_grid[jmin]

    _, imatch = tree.query(np.column_stack(( cos_g*xgrid + sin_g*ygrid,
                                            -sin_g*xgrid + cos_g*ygrid)), k=1, workers=-1)
    imatch = imatch.astype(np.int32)

    if np.unique(imatch).size != imatch.size:
        log.warning("Fiber matching is not unique")
        # log about which number of fibers are not matched

    # 무게중심을 옮긴 만큼을 되돌려 원래 좌표계의 offset으로 바꾼다.
    #   R(t)*obs + D = x  ->  D = off + tgt_c - R(t)*obs_c
    xoff = offset_grid[imin] + tgt_c[0] - (cos_g*obs_c[0] - sin_g*obs_c[1])
    yoff = offset_grid[jmin] + tgt_c[1] - (sin_g*obs_c[0] + cos_g*obs_c[1])

    return imatch, (coeff_temp[1]+theta_guess), (-coeff_temp[2]-xoff, -coeff_temp[3]-yoff)
