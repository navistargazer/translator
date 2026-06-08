import os
import re
import unicodedata


def normalize_nfc(text):
    """
    한글 자소 분리(NFD) 문제를 차단하기 위해 완성형 한글(NFC)로 변환합니다.
    """
    return unicodedata.normalize("NFC", text)


def extract_and_normalize_episode_number(title):
    """
    에피소드 제목에서 숫자 부분만 정밀하게 추출하여 정규화된 형태의 숫자 폴더명으로 변환합니다.
    예:
      '성스러운 소녀와 비...밀스러운 일 001.0화' -> '001.0'
      '성스러운 소녀와 비...밀스러운 일 008.5화' -> '008.5'
      '10권 - 2' -> '10-02'
    """
    try:
        # 1) '[숫자]화' 또는 '[소수]화' 매칭 검사
        match = re.search(r"(\d+(?:\.\d+)?)\s*화", title)
        if match:
            num_str = match.group(1)
            num = float(num_str)
            integer_part = int(num)
            decimal_part = num - integer_part

            # 정수 부분 3자리 패딩 및 소수 첫째자리 고정 포맷 (예: 8 -> '008.0')
            normalized_num_str = f"{integer_part:03d}.{int(round(decimal_part * 10))}"
            return normalized_num_str

        # 2) '권 - [숫자]' 또는 '권-[숫자]' 매칭 검사 (예: 10권 - 2)
        match_vol = re.search(r"(\d+)\s*권\s*-\s*(\d+)", title)
        if match_vol:
            vol = int(match_vol.group(1))
            part = int(match_vol.group(2))
            return f"{vol:02d}-{part:02d}"

        # 3) 일반적인 숫자 추출 시도 (가장 마지막에 나오는 숫자군)
        numbers = re.findall(r"(\d+(?:\.\d+)?)", title)
        if numbers:
            num_str = numbers[-1]
            num = float(num_str)
            integer_part = int(num)
            decimal_part = num - integer_part
            return f"{integer_part:03d}.{int(round(decimal_part * 10))}"
    except Exception:
        pass

    # 만약 정규화가 실패하거나 번호가 아예 없다면 특수문자만 정리해서 반환
    return re.sub(r'[\\/*?:"<>|]', "_", title)


def rename_episodes_to_numbers(manhwa_dir, dry_run=True):
    """
    만화 폴더 안의 회차 서브폴더명들을 오직 숫자 포맷(예: 001.0)으로만 일괄 리네임합니다.
    """
    # 경로 자소 표준화 및 절대경로화
    manhwa_dir = normalize_nfc(os.path.abspath(manhwa_dir))

    if not os.path.exists(manhwa_dir):
        print(f"오류: '{manhwa_dir}' 경로가 존재하지 않습니다.")
        return

    print(
        f"--- 회차 폴더명 ➡️ 숫자로 일괄 변경 시작 ({'미리보기 모드' if dry_run else '실제 적용 모드'}) ---"
    )
    print(f"대상 만화 폴더: {manhwa_dir}\n")

    try:
        items = os.listdir(manhwa_dir)
    except Exception as e:
        print(f"디렉토리 읽기 실패: {e}")
        return

    change_count = 0

    for item in items:
        # 파일은 건너뛰고 디렉토리만 변경
        old_item_nfc = normalize_nfc(item)
        old_path = os.path.join(manhwa_dir, old_item_nfc)
        actual_old_path = os.path.join(manhwa_dir, item)

        if os.path.isdir(actual_old_path):
            # 숫자로만 이루어진 폴더명으로 변환 시도
            new_item_nfc = extract_and_normalize_episode_number(old_item_nfc)
            new_path = os.path.join(manhwa_dir, new_item_nfc)

            # 이미 변환이 적용되어 이름이 같으면 건너뜀
            if old_item_nfc == new_item_nfc:
                continue

            print(f"[변경 대상 감지]")
            print(f"  이전: {old_item_nfc}")
            print(f"  이후: {new_item_nfc}")

            # 이미 동일한 숫자의 폴더가 존재한다면 꼬임 방지를 위해 건너뜀
            if os.path.exists(new_path):
                print(
                    f"  ⚠️ 경고: '{new_item_nfc}' 폴더가 이미 물리적으로 존재하여 이름 변경을 스킵합니다."
                )
                print("-" * 50)
                continue

            if not dry_run:
                try:
                    os.rename(actual_old_path, new_path)
                    print("  ✅ 이름 변경 완료!")
                except Exception as e:
                    print(f"  ❌ 변경 실패: {e}")
            else:
                print("  ℹ️ (미리보기 모드이므로 실제로 변경되지 않았습니다)")

            print("-" * 50)
            change_count += 1

    print(f"\n작업 완료! 총 {change_count}개의 폴더가 매칭되어 처리되었습니다.")
    if dry_run and change_count > 0:
        print(
            "💡 팁: 실제로 반영하시려면 하단의 'DRY_RUN_MODE = True'를 'DRY_RUN_MODE = False'로 바꾸고 실행하세요."
        )


if __name__ == "__main__":
    # ================= 설정 영역 =================
    # 1. 숫자로 바꿀 만화 회차 폴더들이 담긴 부모 폴더 경로
    TARGET_MANHWA_DIRECTORY = (
        "/Volumes/MacSSD/Comics/추방당한 전생 중기사는 게임 지식으로 무쌍한다"
    )

    # 2. 안전 모드 설정 (True: 미리보기, False: 실제 디스크 변경 적용)
    DRY_RUN_MODE = False
    # ============================================

    rename_episodes_to_numbers(manhwa_dir=TARGET_MANHWA_DIRECTORY, dry_run=DRY_RUN_MODE)
