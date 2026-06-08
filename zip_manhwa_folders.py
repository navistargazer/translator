import os
import re
import shutil
import zipfile
import unicodedata
import time


def normalize_nfc(text):
    """
    한글 자소 분리(NFD) 현상을 없애고 표준 완성형(NFC) 한글로 통일합니다.
    윈도우에서 압축을 풀 때 한글 자소가 낱개로 쪼개지는 현상을 방지하는 핵심 함수입니다.
    """
    return unicodedata.normalize("NFC", text)


def zip_folders_for_windows(manhwa_dir, delete_original=False, dry_run=True):
    """
    지정된 만화 폴더 하위의 각 회차 디렉토리들을 윈도우 호환 한글(NFC) 포맷의 .zip 파일로 압축합니다.

    :param manhwa_dir: 회차 폴더들이 모여있는 부모 폴더 (예: "/Volumes/MacSSD/Comics/만화제목")
    :param delete_original: True이면 압축 완료가 검증된 후 원본 폴더를 디스크에서 즉시 삭제합니다.
    :param dry_run: True이면 실제로 압축하지 않고 시뮬레이션 결과만 출력합니다.
    """
    manhwa_dir = normalize_nfc(os.path.abspath(manhwa_dir))

    if not os.path.exists(manhwa_dir):
        print(f"오류: '{manhwa_dir}' 경로가 존재하지 않습니다.")
        return

    print(
        f"--- 윈도우 호환 한글 ZIP 압축 작업 시작 ({'미리보기 모드' if dry_run else '실제 압축 모드'}) ---"
    )
    print(f"대상 만화 폴더: {manhwa_dir}")
    print(f"압축 후 원본 삭제 여부: {delete_original}\n")

    try:
        items = os.listdir(manhwa_dir)
    except Exception as e:
        print(f"디렉토리 읽기 실패: {e}")
        return

    success_count = 0

    for item in items:
        old_item_nfc = normalize_nfc(item)
        src_path = os.path.join(manhwa_dir, item)

        # 회차 폴더(디렉토리)만 타겟으로 삼으며, 이미 압축된 zip 파일 등은 제외
        if os.path.isdir(src_path):
            zip_filename = f"{old_item_nfc}.zip"
            dst_zip_path = os.path.join(manhwa_dir, zip_filename)

            print(f"[압축 대상 폴더 발견]: {old_item_nfc}")
            print(f"  ➡️ 생성될 파일: {zip_filename}")

            if os.path.exists(dst_zip_path):
                print(
                    f"  ⚠️ 경고: 동일한 이름의 압축파일({zip_filename})이 이미 존재하여 작업을 건너뜁니다."
                )
                print("-" * 60)
                continue

            if not dry_run:
                try:
                    # zip 파일 쓰기 모드로 오픈
                    with zipfile.ZipFile(dst_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        # 폴더 내부를 돌며 파일 압축 진행
                        for root, _, files in os.walk(src_path):
                            for file in files:
                                file_path = os.path.join(root, file)

                                # zip 파일 내부에 기록될 상대 경로 셋업
                                rel_path = os.path.relpath(file_path, src_path)

                                # ⭐ 핵심: zip 아카이브에 기록할 경로 문자열을 NFC 완성형 한글로 정밀 정규화
                                nfc_rel_path = normalize_nfc(rel_path)

                                # zipfile 내부에 저장될 ZipInfo 객체를 만들어 한글 깨짐 방지 인코딩 보장
                                zip_info = zipfile.ZipInfo(nfc_rel_path)
                                zip_info.compress_type = zipfile.ZIP_DEFLATED
                                # UTF-8 인코딩 플래그 강제 활성화 (0x800)
                                zip_info.flag_bits |= 0x800
                                # 원본 파일의 시간 정보 복사
                                st = os.stat(file_path)
                                mtime = time_struct = time.localtime(st.st_mtime)

                                zip_info.date_time = mtime[0:6]

                                # 바이너리로 읽어서 쓰기 진행
                                with open(file_path, "rb") as f:
                                    zf.writestr(zip_info, f.read())

                    print("  ✅ ZIP 압축 파일 작성 완료!")

                    # 압축 성공 검증 후 원본 폴더 삭제 처리
                    if delete_original:
                        # 압축 파일이 정상적으로 써졌는지 간이 크기 체크 검증
                        if (
                            os.path.exists(dst_zip_path)
                            and os.path.getsize(dst_zip_path) > 0
                        ):
                            shutil.rmtree(src_path)
                            print("  🗑️ 원본 폴더 삭제 완료.")
                        else:
                            print("  ❌ 압축 파일 검증 실패로 원본 폴더를 유지합니다.")

                except Exception as e:
                    print(f"  ❌ 압축 실패: {e}")
                    # 실패 시 찌꺼기 zip 파일 삭제
                    if os.path.exists(dst_zip_path):
                        os.remove(dst_zip_path)
            else:
                print("  ℹ️ (미리보기 모드이므로 실제 압축 파일이 생성되지 않았습니다)")

            print("-" * 60)
            success_count += 1

    print(f"\n작업 완료! 총 {success_count}개의 폴더가 처리되었습니다.")
    if dry_run and success_count > 0:
        print(
            "💡 팁: 실제로 압축하시려면 하단의 'DRY_RUN_MODE = True'를 'DRY_RUN_MODE = False'로 변경하여 실행해 주세요."
        )


if __name__ == "__main__":
    # ================= 설정 영역 =================
    # 1. 하위 에피소드 폴더들을 zip으로 압축할 부모 만화 폴더 경로를 입력하세요.
    TARGET_MANHWA_DIRECTORY = "/Volumes/MacSSD/Comics/성스러운 소녀와 비밀스러운 일"

    # 2. 압축 완료 검증 후 원본 에피소드 폴더를 삭제할지 여부 (안전을 위해 처음에는 False 권장)
    DELETE_ORIGINAL_FOLDERS = False

    # 3. 안전 모드 설정 (True: 미리보기만 실행, False: 실제 디스크 압축 파일 생성 및 변환)
    DRY_RUN_MODE = False
    # ============================================

    zip_folders_for_windows(
        manhwa_dir=TARGET_MANHWA_DIRECTORY,
        delete_original=DELETE_ORIGINAL_FOLDERS,
        dry_run=DRY_RUN_MODE,
    )
