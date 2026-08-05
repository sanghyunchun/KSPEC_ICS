import kspec_0724_control as mvf

# # rotate_one() 
# # 축 하나 돌리고 싶을때
# result = mvf.rotate_one(positioner="A1", motor="alpha", angle=70)
# print(result)


# # show_status()
# # 포지셔너 하나의 상태를 보고 싶을 때
# result = mvf.show_status(axis="A1")
# print(result)


# positioner_lock
# 잠금 후 실행시 충돌 안전은 보장하지 않음.
# if __name__ == "__main__":
#     result = mvf.positioner_lock(["A1", "A2", "A3", "A5"]) #lock 풀고싶다면 []안에 빈칸 유지
#     print(result)



# ######################################################################

# main() 실행
# python kspec_run.py
# if __name__ == "__main__":
#     mvf.main()


# reverse_main() 실행
# python kspec_run.py
# if __name__ == "__main__":
#     mvf.reverse_main()


# # zero_main() 실행
# # python kspec_run.py
if __name__ == "__main__":
    mvf.zero_main()


# # 정지 지점에서 1단계로 역방향 복귀
# if __name__ == "__main__":
#     mvf.reverse_from_stop_step()