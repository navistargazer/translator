import os
import re
import unicodedata

def normalize_nfc(text):
    """
    한글 자소 분리(NFD) 현상으로 인한 매칭 실패 및 파일 시스템 꼬임 방지를 위해
    문자열을 표준 완성형 한글(NFC) 형태로 강제 변환합니다.
    """
    return unicodedata.normalize('NFC', text)

def rename_folders_regex(parent_dir, pattern_str, replacement_str, dry_run=True):
    """
    지정된 부모 디렉토리 내의 폴더명 중 정규식 패턴과 매치되는 부분을 찾아 다른 문자열로 변경합니다.
    자소 분리(NFD) 문제를 원천 예방하기 위해 모든 경로 비교와 이름 생성을 NFC 완성형으로 정규화합니다.
    """
    # 부모 경로 정규화
    parent_dir = normalize_nfc(os.path.abspath(parent_dir))
    
    if not os.path.exists(parent_dir):
        print(f"오류: '{parent_dir}' 경로가 존재하지 않습니다.")
        return
        
    print(f"--- 폴더 이름 일괄 변경 시작 (정규식 지원 + NFC 자소 표준화 / {'미리보기 모드' if dry_run else '실제 적용 모드'}) ---")
    print(f"부모 경로: {parent_dir}")
    print(f"매칭 패턴: '{pattern_str}' ➡️ 바꿀 문자열: '{replacement_str}'\n")
    
    try:
        # 정규식 패턴도 안전하게 NFC 표준화하여 컴파일
        regex = re.compile(normalize_nfc(pattern_str))
    except re.error as e:
        print(f"⚠️ 정규식 패턴 문법 에러: {e}")
        return

    try:
        items = os.listdir(parent_dir)
    except Exception as e:
        print(f"디렉토리 읽기 실패: {e}")
        return

    change_count = 0
    
    for item in items:
        # 읽어온 폴더명을 즉시 NFC 표준 완성형으로 통일
        item_nfc = normalize_nfc(item)
        old_path = os.path.join(parent_dir, item_nfc)
        
        # 실제 OS 시스템 상에서 자소 분리 형태(NFD)로 되어있을 수 있으므로 
        # 원본 실물 경로도 안전하게 확보
        actual_old_path = os.path.join(parent_dir, item)
        
        if os.path.isdir(actual_old_path):
            # 정규식 매칭 수행 (NFC 통일 상태에서 검사)
            if regex.search(item_nfc):
                # 패턴 치환 및 신규 폴더명 생성
                new_item = regex.sub(replacement_str, item_nfc)
                new_item_nfc = normalize_nfc(new_item)
                new_path = os.path.join(parent_dir, new_item_nfc)
                
                # 만약 기존 폴더명과 바뀔 폴더명이 바이트 단위까지 완전 일치한다면 스킵
                if item_nfc == new_item_nfc:
                    continue
                
                print(f"[매칭 발견]")
                print(f"  이전: {item_nfc}")
                print(f"  이후: {new_item_nfc}")
                
                # 🛑 초강력 이중 안전장치: 자소 융합(NFC) 기준으로 이미 폴더가 있는지 확실하게 검사
                if os.path.exists(new_path):
                    print(f"  ⚠️ 경고: '{new_item_nfc}' 폴더가 이미 물리적으로 존재합니다. 폴더 빨려들어감 방지를 위해 변경을 건너뜁니다.")
                    print("-" * 50)
                    continue
                
                if not dry_run:
                    try:
                        os.rename(actual_old_path, new_path)
                        print("  ✅ 이름 변경 완료!")
                    except Exception as e:
                        print(f"  ❌ 변경 실패: {e}")
                else:
                    print("  ℹ️ (미리보기 모드이므로 실제 변경되지 않았습니다)")
                
                print("-" * 50)
                change_count += 1
                
    print(f"\n작업 완료! 총 {change_count}개의 폴더가 매칭되었습니다.")
    if dry_run and change_count > 0:
        print("💡 팁: 실제로 반영하시려면 함수 호출부의 'dry_run=True'를 'dry_run=False'로 변경하고 실행해 주세요.")

if __name__ == "__main__":
    # ================= 설정 영역 =================
    # 1. 만화 폴더가 들어있는 최상위 부모 경로 지정
    TARGET_PARENT_DIRECTORY = "/Volumes/MacSSD/Comics/성스러운 소녀와 비밀스러운 일" 
    
    # 2. 정규식 매칭 패턴 및 바꿀 문자열 지정
    # '비'로 시작해서 중간에 무작위 문자들(말줄임표 등)이 온 뒤 '운'으로 끝나는 패턴을 찾습니다.
    # r"비.*?운"은 와일드카드 '비*운'에 상응하는 정규식 패턴입니다.
    FIND_PATTERN = r"비.*?운"
    REPLACE_TEXT = "비밀스러운"
    
    # 3. 안전 모드 설정 (True: 미리보기만 실행, False: 실제 폴더명 변경 적용)
    DRY_RUN_MODE = False
    # ============================================

    rename_folders_regex(
        parent_dir=TARGET_PARENT_DIRECTORY,
        pattern_str=FIND_PATTERN,
        replacement_str=REPLACE_TEXT,
        dry_run=DRY_RUN_MODE
    )

