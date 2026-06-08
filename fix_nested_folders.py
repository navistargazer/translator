import os
import shutil


def fix_nested_folders(target_dir):
    """
    중복 경로로 중첩 생성된 폴더 구조를 복구합니다.
    예: '.../에피소드_004.5화/만화제목/에피소드_004.5화/001.jpg'
    하위의 깊숙이 들어있는 이미지들을 상위의 에피소드 폴더로 이동시키고 빈 중첩 폴더를 삭제합니다.
    """
    if not os.path.exists(target_dir):
        print(f"오류: '{target_dir}' 경로가 존재하지 않습니다.")
        return

    print(f"--- 중첩 폴더 복구 작업 시작 ---")
    print(f"대상 만화 폴더: {target_dir}\n")

    # 1단계: 만화 폴더 내의 에피소드 폴더들을 탐색
    try:
        episodes = os.listdir(target_dir)
    except Exception as e:
        print(f"디렉토리 읽기 실패: {e}")
        return

    fixed_count = 0

    for ep in episodes:
        ep_path = os.path.join(target_dir, ep)
        if not os.path.isdir(ep_path):
            continue

        # 에피소드 폴더 내부를 조사
        # 하위에 원래 만화 제목과 동일한 이름의 서브폴더가 또 있는지 확인
        try:
            sub_items = os.listdir(ep_path)
        except Exception:
            continue

        for sub in sub_items:
            sub_path = os.path.join(ep_path, sub)
            if not os.path.isdir(sub_path):
                continue

            # 서브폴더 내부로 한 번 더 들어감 (중첩된 에피소드 폴더가 있는지 탐색)
            try:
                deep_items = os.listdir(sub_path)
            except Exception:
                continue

            for deep in deep_items:
                deep_path = os.path.join(sub_path, deep)
                if not os.path.isdir(deep_path):
                    continue

                # 에피소드 번호 키워드가 일치하거나 중첩 구조가 명확할 때 처리
                # 예: ep='성스러운...004.5화' 이고 deep='성스러운...004.5화' 인 경우
                # 혹은 단순히 deep 폴더 내부에 이미지 파일이 들어있는 경우
                try:
                    files = os.listdir(deep_path)
                except Exception:
                    continue

                images = [
                    f
                    for f in files
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
                ]

                if images:
                    print(f"[중첩 중복 폴더 발견!]")
                    print(f"  상위 에피소드: {ep_path}")
                    print(f"  하위 중첩 경로: {deep_path}")
                    print(f"  이동할 이미지 수: {len(images)}개")

                    # 파일 이동 작업 수행
                    moved_files = 0
                    for img in images:
                        src_file = os.path.join(deep_path, img)
                        dst_file = os.path.join(ep_path, img)

                        try:
                            # 덮어쓰기 방지하며 이동
                            if not os.path.exists(dst_file):
                                shutil.move(src_file, dst_file)
                                moved_files += 1
                        except Exception as e:
                            print(f"    ❌ 파일 이동 실패 ({img}): {e}")

                    print(f"  ➡️ {moved_files}개 이미지 이동 완료")

                    # 2단계: 이미지 이동 후 중첩된 빈 서브폴더 트리 삭제
                    try:
                        # shutil.rmtree를 사용하여 빈 만화제목/에피소드제목 통째로 삭제
                        shutil.rmtree(sub_path)
                        print(f"  ✅ 중첩되었던 빈 폴더 구조({sub_path}) 삭제 완료!")
                        fixed_count += 1
                    except Exception as e:
                        print(f"  ❌ 빈 폴더 삭제 실패: {e}")

                    print("-" * 60)

    print(f"\n복구 완료! 총 {fixed_count}개의 중첩 에피소드 폴더가 복구되었습니다.")


if __name__ == "__main__":
    # ================= 복구 설정 영역 =================
    # 꼬인 폴더가 들어있는 만화 디렉토리 경로를 지정하세요.
    # 예: "/Volumes/MacSSD/Comics/성스러운 소녀와 비밀스러운 일"
    TARGET_MANHWA_DIRECTORY = (
        "/Volumes/MacSSD/Comics/추방당한 전생 중기사는 게임 지식으로 무쌍한다"
    )
    # ============================================

    fix_nested_folders(TARGET_MANHWA_DIRECTORY)
