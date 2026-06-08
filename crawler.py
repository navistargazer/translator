import os
import re
import time
import shutil
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, quote, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup



def safe_url_encode(url):
    """
    URL에 한글 등 비ASCII 문자가 포함된 경우 안전하게 퍼센트 인코딩합니다.
    이를 통해 HTTP 헤더(Referer 등) 전송 시 'latin-1' 인코딩 에러를 방지합니다.
    """
    try:
        parsed = urlparse(url)
        quoted_path = quote(parsed.path)
        quoted_query = quote(parsed.query, safe="=&%")
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            quoted_path,
            parsed.params,
            quoted_query,
            parsed.fragment
        ))
    except Exception:
        return url


def normalize_episode_title(title):
    """
    회차명 내부의 숫자를 찾아 자릿수를 정규화(패딩)하여 탐색기 상의 수학적 정렬 순서를 보장합니다.
    예: '8화' -> '008.0화', '8.5화' -> '008.5화', '10권 - 2' -> '10권 - 02'
    이를 통해 웹페이지의 무작위 게시 순서와 상관없이 오직 수학적 회차 순번으로 Finder 정렬이 이루어집니다.
    """
    try:
        # 0) '[숫자]-[숫자]화' 또는 '[소수]-[숫자]화' 매칭 검사 (예: 81-2화) -> 1번 규칙보다 먼저 매칭해야 함
        match_dash = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+)\s*화", title)
        if match_dash:
            full_match = match_dash.group(0)
            num1_str = match_dash.group(1)
            num2_str = match_dash.group(2)
            
            num1 = float(num1_str)
            integer_part = int(num1)
            decimal_part = num1 - integer_part
            
            # 앞부분 정수 3자리 패딩 및 소수 첫째자리 고정 포맷 (예: 81 -> 081.0, 81.5 -> 081.5)
            normalized_num1 = f"{integer_part:03d}.{int(round(decimal_part * 10))}"
            part = int(num2_str)
            # 뒷부분(파트)은 2자리 패딩
            normalized_match = f"{normalized_num1}-{part:02d}화"
            return title.replace(full_match, normalized_match)

        # 1) '[숫자]화' 또는 '[소수]화' 매칭 검사
        match = re.search(r"(\d+(?:\.\d+)?)\s*화", title)
        if match:
            full_match = match.group(0)  # "8화"
            num_str = match.group(1)     # "8"
            
            num = float(num_str)
            integer_part = int(num)
            decimal_part = num - integer_part
            
            # 정수 부분 3자리 패딩 및 소수 첫째자리 고정 포맷 (예: 8 -> 008.0, 8.5 -> 008.5)
            normalized_num_str = f"{integer_part:03d}.{int(round(decimal_part * 10))}"
            normalized_match = f"{normalized_num_str}화"
            
            return title.replace(full_match, normalized_match)

        # 2) '권 - [숫자]' 또는 '권-[숫자]' 매칭 검사 (예: 10권 - 2)
        match_vol = re.search(r"(\d+)\s*권\s*-\s*(\d+)", title)
        if match_vol:
            full_match = match_vol.group(0)
            vol = int(match_vol.group(1))
            part = int(match_vol.group(2))
            
            # 권은 2자리, 부는 2자리 패딩 적용
            normalized_vol_str = f"{vol:02d}권 - {part:02d}"
            return title.replace(full_match, normalized_vol_str)
            
    except Exception:
        pass
    return title


def extract_and_normalize_episode_number(title):
    """
    에피소드 제목에서 숫자 부분만 정밀하게 추출하여 정규화된 형태의 숫자 폴더명으로 변환합니다.
    예:
      '성스러운 소녀와 비...밀스러운 일 8화' -> '008.0'
      '성스러운 소녀와 비...밀스러운 일 8.5화' -> '008.5'
      '10권 - 2' -> '10-02'
      '허구추리 81-2화' -> '081.0-02'
    """
    try:
        # 0) '[숫자]-[숫자]화' 또는 '[소수]-[숫자]화' 매칭 검사 (예: 81-2화) -> 1번 규칙보다 먼저 매칭해야 함
        match_dash = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+)\s*화", title)
        if match_dash:
            num1_str = match_dash.group(1)
            num2_str = match_dash.group(2)
            
            num1 = float(num1_str)
            integer_part = int(num1)
            decimal_part = num1 - integer_part
            
            normalized_num1 = f"{integer_part:03d}.{int(round(decimal_part * 10))}"
            part = int(num2_str)
            return f"{normalized_num1}-{part:02d}"

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


def _download_single_image(session, img_url, filepath, img_headers, max_retries=3):
    """단일 이미지를 안전하게 다운로드하여 디스크에 저장하는 스레드 타겟 함수"""
    # 5개 스레드가 일시에 요청을 보낼 때 발생하는 차단(DDoS 탐지)을 완화하기 위해 미세한 무작위 초기 지터 도입
    time.sleep(random.uniform(0.05, 0.25))
    
    for attempt in range(1, max_retries + 1):
        try:
            # session을 통해 커넥션을 재활용하여 다운로드 요청
            response = session.get(img_url, headers=img_headers, timeout=15)
            
            # HTTP 429 Too Many Requests 또는 HTTP 403 Forbidden 검출 (차단 또는 제한 징후)
            if response.status_code in (429, 403):
                # block을 회피하기 위해 대기 시간을 크게 갖는 백오프 적용
                backoff_time = attempt * 5 + random.uniform(1, 3)
                print(f"\n[경고] HTTP {response.status_code} 발생 (차단 방지 백오프 {backoff_time:.2f}초 대기 중...)")
                time.sleep(backoff_time)
                continue

            if response.status_code == 200:
                # 임시 파일 저장 후 이름 바꾸기로 파일 오염 방지
                temp_filepath = filepath + ".tmp"
                with open(temp_filepath, "wb") as f:
                    f.write(response.content)
                os.replace(temp_filepath, filepath)
                return True
            else:
                if attempt < max_retries:
                    sleep_time = attempt * 1.5 + random.uniform(0.5, 1.5)
                    time.sleep(sleep_time)
        except Exception:
            if attempt < max_retries:
                sleep_time = attempt * 1.5 + random.uniform(0.5, 1.5)
                time.sleep(sleep_time)
    return False


def download_board_images(url, download_folder="downloaded_images", run_cleanup=True, session=None):
    # URL 안전 인코딩
    url = safe_url_encode(url)

    # 1. 봇 차단 방지를 위한 브라우저 헤더 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    # session이 지정되지 않은 단독 실행의 경우 임시 세션 개설
    local_session = False
    if session is None:
        session = requests.Session()
        local_session = True

    try:
        # 2. 게시판 페이지 HTML 가져오기
        print("페이지 요청 중...")
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # 인코딩 설정 (한글 깨짐 방지)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        # 3. 에피소드 및 만화 제목 추출하여 안전한 중첩 저장 폴더 생성 (기본폴더/만화제목/회차제목)
        # 에피소드 제목 추출
        episode_title = ""
        title_span = soup.find("span", class_="viewer-header__title")
        if title_span:
            episode_title = title_span.get_text(strip=True)
        else:
            title_text = soup.title.string if soup.title else ""
            episode_title = title_text.split("-")[0].strip() if "-" in title_text else "Episode"
        
        # 에피소드 제목에서 숫자 포맷만 추출하여 폴더명으로 지정 (예: '001.0')
        clean_episode_title = extract_and_normalize_episode_number(episode_title)

        # 만화 제목 추출 (stx 파라미터 활용)
        from urllib.parse import parse_qs
        parsed_url = urlparse(url)
        queries = parse_qs(parsed_url.query)
        comic_title = queries.get("stx", [""])[0].strip()
        if not comic_title:
            comic_title = "Comic"
        clean_comic_title = re.sub(r'[\\/*?:"<>|]', "_", comic_title)

        # 이미 경로 내에 에피소드 폴더가 중첩 설계되어 있지 않은 단독 요청의 경우, 경로를 확장합니다.
        norm_folder = os.path.normpath(download_folder)
        is_already_nested = False
        base_name = os.path.basename(norm_folder)
        
        # 1) 단순 포함 체크
        if clean_episode_title in norm_folder:
            is_already_nested = True
        # 2) 폴더명이 정규화로 이름이 바뀌었더라도 에피소드 번호가 일치하면 중첩 폴더로 인정 (이중 생성 방지)
        else:
            ep_num_match = re.search(r"(\d+\.\d+)", clean_episode_title)
            if ep_num_match:
                ep_num = ep_num_match.group(1)
                # 현재 폴더명 끝자락에 해당 회차 번호가 이미 매칭되어 있다면 중복 확장 생략
                if ep_num in base_name:
                    is_already_nested = True
                    
        if not is_already_nested:
            download_folder = os.path.join(download_folder, clean_comic_title, clean_episode_title)

        # 저장할 최종 폴더 생성
        if not os.path.exists(download_folder):
            os.makedirs(download_folder)
            print(f"[{download_folder}] 폴더를 생성했습니다.")

        # 4. 본문 이미지 추출
        # 대상 사이트는 본문 만화 이미지를 HTML <img> 태그가 아닌 JavaScript 변수(img_list)에 배열 형태로 동적으로 담아 로드합니다.
        # 따라서 JavaScript 소스 내의 img_list 변수에서 이미지 URL 목록을 추출합니다.
        img_urls = []
        js_match = re.search(r'var\s+img_list\s*=\s*(\[[^\]]*\]);', response.text)
        if js_match:
            try:
                import json
                img_urls = json.loads(js_match.group(1))
                print(f"JavaScript 변수(img_list)에서 이미지 {len(img_urls)}개를 감지했습니다.")
            except Exception as e:
                print(f"JavaScript 이미지 목록 파싱 실패: {e}")

        # 만약 JavaScript 변수에서 찾지 못했다면 기존 HTML img 태그 방식 사용
        if not img_urls:
            view_content = soup.find(id="bo_v_atc") or soup.find(class_="write_div")
            if not view_content:
                print("특정 본문 태그를 찾지 못해 전체 페이지의 이미지를 검색합니다.")
                view_content = soup

            img_tags = view_content.find_all("img")
            print(f"HTML img 태그 검색 결과 찾은 이미지 태그 수: {len(img_tags)}개")
            for img in img_tags:
                img_url = img.get("src")
                if img_url:
                    img_urls.append(img_url)

        # 다운로드 태스크 생성 및 기다운로드 패스 검사
        tasks_to_run = []
        img_count = 1
        total_images = len(img_urls)
        skipped_count = 0
        
        for img_url in img_urls:
            # 상대 경로인 경우 절대 경로로 변환
            img_url = urljoin(url, img_url)
            img_url = safe_url_encode(img_url)

            # 불필요한 이모티콘이나 외부 아이콘 제외 필터링 (선택 사항)
            if "icon" in img_url or "emoticon" in img_url:
                total_images -= 1
                continue

            # 파일 확장자 추출 (없으면 jpg로 기본 지정)
            ext_match = re.search(r"\.(jpg|jpeg|png|gif|webp)", img_url, re.IGNORECASE)
            ext = ext_match.group(1) if ext_match else "jpg"

            # 안전한 파일명 생성 (001.jpg, 002.jpg ...)
            filename = f"{img_count:03d}.{ext}"
            filepath = os.path.join(download_folder, filename)
            img_count += 1

            # 이미 다운로드된 정상 파일(용량이 0보다 큰 파일)이 있으면 스킵하여 네트워크 요청 절약
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                skipped_count += 1
                continue

            # 5. 이미지 다운로드 요청 준비
            img_headers = headers.copy()
            img_headers["Referer"] = url
            tasks_to_run.append((img_url, filepath, img_headers))

        # 동기화 락 및 카운터 정의
        print_lock = threading.Lock()
        completed_count = skipped_count

        if skipped_count > 0:
            print(f"-> 기존 파일 존재로 {skipped_count}개 다운로드 건너뜀.")

        # 스레드 풀 워커 정의
        def worker(task):
            nonlocal completed_count
            t_url, t_path, t_headers = task
            success = _download_single_image(session, t_url, t_path, t_headers)
            with print_lock:
                completed_count += 1
                print(f"\r-> 이미지 다운로드 진행 중... ({completed_count}/{total_images})", end="", flush=True)
            return success

        # 5개 워커 스레드로 병렬 처리 진행
        if tasks_to_run:
            with ThreadPoolExecutor(max_workers=5) as executor:
                executor.map(worker, tasks_to_run)

        # 진행률 표시 마무리 개행
        print()
        print(
            f"완료: '{download_folder}' 폴더에 총 {total_images}개 이미지 저장 완료."
        )

        # 중첩 폴더 복구 실행
        if run_cleanup:
            try:
                parent_dir = os.path.dirname(os.path.normpath(download_folder))
                if parent_dir and os.path.exists(parent_dir):
                    print("\n[안내] 다운로드 완료 후 중첩 폴더 자동 복구를 수행합니다...")
                    fix_nested_folders(parent_dir)
            except Exception as e:
                print(f"중첩 폴더 복구 중 오류 발생: {e}")

    except Exception as e:
        print(f"페이지 접속 실패: {e}")
    finally:
        if local_session:
            session.close()


def download_series(list_url, base_folder="downloaded_images"):
    # 저장할 부모 폴더 생성
    if not os.path.exists(base_folder):
        os.makedirs(base_folder)
        print(f"부모 폴더 [{base_folder}]를 생성했습니다.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    # 전체 시리즈 다운로드 동안 커넥션을 풀링할 단일 세션 개설
    session = requests.Session()
    try:
        print("회차 목록 페이지 요청 중...")
        response = session.get(list_url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        # 회차 리스트 파싱
        episodes = []
        buttons = soup.find_all("button", class_="episode")
        for button in buttons:
            onclick = button.get("onclick", "")
            url_match = re.search(r"location\.href\s*=\s*[`'\"]([^`'\"]+)[`'\"]", onclick)
            if url_match:
                episode_url = url_match.group(1)
                title_div = button.find(class_="episode-title")
                if title_div:
                    episode_title = title_div.get_text(strip=True)
                    # 에피소드 제목에서 숫자 포맷만 추출하여 폴더명으로 지정 (예: '001.0')
                    clean_title = extract_and_normalize_episode_number(episode_title)
                    episodes.append({
                        "url": urljoin(list_url, episode_url),
                        "title": clean_title
                    })

        if not episodes:
            print("회차 목록을 찾지 못했습니다. HTML 구조가 변경되었는지 확인해주세요.")
            return

        # 만화 제목 추출 (h2 class="title" 영역 감지)
        title_tag = soup.find("h2", class_="title")
        if title_tag:
            comic_title = title_tag.get_text(strip=True)
        else:
            title_text = soup.title.string if soup.title else ""
            comic_title = title_text.split("-")[0].strip() if "-" in title_text else "Comic"
        clean_comic_title = re.sub(r'[\\/*?:"<>|]', "_", comic_title)

        # 만화 제목 폴더를 포함한 최종 부모 경로 설정
        series_folder = os.path.join(base_folder, clean_comic_title)
        if not os.path.exists(series_folder):
            os.makedirs(series_folder)
            print(f"만화 제목 폴더 [{series_folder}]를 생성했습니다.")

        # 최신화가 위에 있으므로 옛날 회차(1화)부터 순서대로 다운로드하기 위해 리스트 순서 뒤집기
        episodes.reverse()

        total_eps = len(episodes)
        print(f"총 {total_eps}개의 회차를 발견했습니다. 순서대로 다운로드를 시작합니다.\n")

        for idx, ep in enumerate(episodes, 1):
            print(f"\n>>> [{idx}/{total_eps}] {ep['title']} 다운로드 시작")
            # 수학적 순서 정규화가 적용된 제목을 그대로 활용하여 폴더명을 지정합니다.
            episode_folder = os.path.join(series_folder, ep["title"])
            download_board_images(ep["url"], download_folder=episode_folder, run_cleanup=False, session=session)
            print("-" * 60)

        print(f"\n🎉 축하합니다! 모든 회차({total_eps}개)의 다운로드가 성공적으로 완료되었습니다.")
        
        # 전체 다운로드 완료 후 중첩 폴더 복구 실행
        try:
            print("\n[안내] 모든 다운로드가 완료되어 중첩 폴더 자동 복구를 수행합니다...")
            fix_nested_folders(series_folder)
        except Exception as e:
            print(f"중첩 폴더 복구 중 오류 발생: {e}")

    except Exception as e:
        print(f"목록 페이지 접속 실패: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    # 단일 회차 또는 전체 목록 페이지 URL 모두 입력 가능합니다.
    # 'wr_id=' 파라미터 유무에 따라 다운로드 모드를 자동으로 판별합니다.
    target_url = "http://103.204.13.68:8904/bbs/board.php?bo_table=toons&stx=%EB%8B%A4%EC%B9%B4%EC%8A%A4%EA%B8%B0%EA%B0%80%EC%9D%98%20%EB%8F%84%EC%8B%9C%EB%9D%BD&is=11838"

    if "wr_id=" in target_url:
        print("단일 회차 다운로드 모드로 시작합니다...")
        download_board_images(target_url, download_folder="다카스기의_도시락")
    else:
        print("전체 시리즈 다운로드 모드로 시작합니다...")
        download_series(target_url, base_folder="다카스기의_도시락")