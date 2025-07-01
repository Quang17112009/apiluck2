from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime
import collections

app = Flask(__name__)

# --- Cấu hình API bên ngoài ---
# THAY THẾ URL NÀY BẰNG URL API THỰC TẾ CỦA BẠN!
EXTERNAL_API_URL = "https://1.bot/GetNewLottery/LT_Taixiu" # Ví dụ: "https://your-actual-external-api.com/GetNewLottery/LT_Taixiu"

# --- Biến toàn cục để lưu trạng thái và lịch sử (KHÔNG PHÙ HỢP CHO SẢN XUẤT LỚN) ---
# Trong môi trường sản xuất thực tế, bạn NÊN sử dụng cơ sở dữ liệu (PostgreSQL, MongoDB, Redis)
# để lưu trữ lịch sử và trạng thái một cách bền vững và đồng bộ.
# Sử dụng deque để giới hạn kích thước lịch sử
history = collections.deque(maxlen=10) # Lưu 10 phiên gần nhất
current_prediction_state = {
    "Phien_moi": None,
    "pattern_length": 8,
    "pattern": "",
    "matches": [],
    "pattern_tai": 0,
    "pattern_xiu": 0,
    "pattern_percent_tai": 0,
    "pattern_percent_xiu": 0,
    "phan_tram_tai": 50, # Mặc định
    "phan_tram_xiu": 50, # Mặc định
    "tong_tai": 0.0,
    "tong_xiu": 0.0,
    "du_doan": "Không xác định",
    "ly_do": "Chưa có dữ liệu dự đoán.",
    "phien_du_doan": None,
    "consecutive_losses": 0 # Theo dõi số lần trật liên tiếp
}

# --- Hàm hỗ trợ ---
def calculate_tai_xiu(open_code_str):
    """Tính tổng xúc xắc và xác định Tài/Xỉu."""
    try:
        dice_values = [int(x) for x in open_code_str.split(',')]
        total_sum = sum(dice_values)

        if total_sum >= 4 and total_sum <= 10:
            return "Xỉu", total_sum
        elif total_sum >= 11 and total_sum <= 17:
            return "Tài", total_sum
        else: # Tổng 3 hoặc 18 (Bộ ba)
            if total_sum == 3: return "Xỉu (Triple)", total_sum # Có thể cần xử lý đặc biệt cho Triple
            if total_sum == 18: return "Tài (Triple)", total_sum # Có thể cần xử lý đặc biệt cho Triple
            return "Không xác định", total_sum
    except Exception as e:
        print(f"Lỗi khi tính Tài/Xỉu: {e}")
        return "Lỗi", 0

def update_pattern_and_matches():
    global current_prediction_state
    
    # Tạo pattern từ lịch sử
    current_prediction_state['pattern'] = ""
    for entry in history:
        result_type, _ = calculate_tai_xiu(entry['OpenCode'])
        if "Tài" in result_type:
            current_prediction_state['pattern'] += 't'
        elif "Xỉu" in result_type:
            current_prediction_state['pattern'] += 'x'
        else:
            current_prediction_state['pattern'] += '?' # Trường hợp không xác định

    # Giới hạn pattern_length
    current_prediction_state['pattern'] = current_prediction_state['pattern'][-current_prediction_state['pattern_length']:]

    # Cập nhật pattern_tai, pattern_xiu và phần trăm
    tai_count = current_prediction_state['pattern'].count('t')
    xiu_count = current_prediction_state['pattern'].count('x')
    
    current_prediction_state['pattern_tai'] = tai_count
    current_prediction_state['pattern_xiu'] = xiu_count

    total_pattern_chars = len(current_prediction_state['pattern'])
    if total_pattern_chars > 0:
        current_prediction_state['pattern_percent_tai'] = (tai_count / total_pattern_chars) * 100
        current_prediction_state['pattern_percent_xiu'] = (xiu_count / total_pattern_chars) * 100
    else:
        current_prediction_state['pattern_percent_tai'] = 0
        current_prediction_state['pattern_percent_xiu'] = 0

    # `matches` có vẻ như là các ký tự trong pattern mà "trùng" với một mẫu nào đó.
    # Để đơn giản, tôi sẽ giả định nó là ký tự đại diện cho kết quả dự đoán của phiên trước.
    # Đây là một giả định, bạn cần làm rõ logic này.
    if history:
        last_prediction_result, _ = calculate_tai_xiu(history[-1]['OpenCode'])
        if "Tài" in last_prediction_result:
            current_prediction_state['matches'] = ['t']
        elif "Xỉu" in last_prediction_result:
            current_prediction_state['matches'] = ['x']
        else:
            current_prediction_state['matches'] = ['?']
    else:
        current_prediction_state['matches'] = []


def perform_prediction_logic():
    """Thực hiện logic dự đoán dựa trên trạng thái hiện tại."""
    global current_prediction_state

    # Cập nhật tổng Tài/Xỉu (nếu bạn có dữ liệu về số tiền hoặc số lượng người chơi)
    # Vì không có dữ liệu này, tôi sẽ mô phỏng dựa trên tỷ lệ phần trăm.
    # Trong thực tế, 'tong_tai' và 'tong_xiu' sẽ đến từ API bên ngoài hoặc tính toán từ dữ liệu cược.
    # Giả định đơn giản: nếu phan_tram_tai > phan_tram_xiu, thì tổng tài > tổng xỉu
    if current_prediction_state['phan_tram_tai'] > current_prediction_state['phan_tram_xiu']:
        current_prediction_state['tong_tai'] = 55.0
        current_prediction_state['tong_xiu'] = 45.0
    else:
        current_prediction_state['tong_tai'] = 45.0
        current_prediction_state['tong_xiu'] = 55.0

    du_doan_ket_qua = ""
    ly_do_du_doan = ""

    # Logic 1: Dựa vào tỷ lệ phần trăm (giả định phan_tram_tai/xiu đến từ đâu đó)
    if current_prediction_state['phan_tram_tai'] > current_prediction_state['phan_tram_xiu']:
        du_doan_ket_qua = "Tài"
        ly_do_du_doan = "Theo tỷ lệ Tài lớn hơn."
    elif current_prediction_state['phan_tram_xiu'] > current_prediction_state['phan_tram_tai']:
        du_doan_ket_qua = "Xỉu"
        ly_do_du_doan = "Theo tỷ lệ Xỉu lớn hơn."
    else:
        # Nếu bằng nhau, có thể dựa vào pattern hoặc random
        if current_prediction_state['pattern_percent_tai'] >= current_prediction_state['pattern_percent_xiu']:
             du_doan_ket_qua = "Tài"
             ly_do_du_doan = "Theo tỷ lệ pattern Tài lớn hơn hoặc bằng."
        else:
             du_doan_ket_qua = "Xỉu"
             ly_do_du_doan = "Theo tỷ lệ pattern Xỉu lớn hơn."

    # Logic 2: "Đang trật X lần → Auto đảo ngược"
    # Đây là logic phức tạp cần lịch sử và so sánh.
    # Ở đây, chúng ta sẽ mô phỏng nó bằng `consecutive_losses`.
    # Nếu `consecutive_losses` đạt đến ngưỡng (ví dụ 3 lần), đảo ngược dự đoán.
    if current_prediction_state['consecutive_losses'] >= 3: # Ngưỡng đảo ngược
        if du_doan_ket_qua == "Tài":
            du_doan_ket_qua = "Xỉu"
        else:
            du_doan_ket_qua = "Tài"
        ly_do_du_doan += " | Đang trật 3 lần → Auto đảo ngược"
        # Sau khi đảo ngược, reset số lần trật liên tiếp (hoặc bạn có thể có logic khác)
        # current_prediction_state['consecutive_losses'] = 0 # Có thể reset tại đây hoặc khi có kết quả chính xác


    current_prediction_state['du_doan'] = du_doan_ket_qua
    current_prediction_state['ly_do'] = ly_do_du_doan
    # Cập nhật phien_du_doan cho phiên tiếp theo
    if current_prediction_state['Phien_moi']:
        # Extract the numeric part of Expect to increment
        try:
            # Assuming Expect is "YYMMDDHHMMSS"
            expect_num = int(current_prediction_state['Expect'])
            current_prediction_state['phien_du_doan'] = str(expect_num + 1)
        except (ValueError, TypeError):
            # Fallback if Expect is not purely numeric or has a complex format
            current_prediction_state['phien_du_doan'] = f"{current_prediction_state['Phien_moi'] + 1}"
    else:
        current_prediction_state['phien_du_doan'] = "Chưa xác định"


@app.route('/')
def home():
    return "Chào mừng đến với API dự đoán Tài Xỉu trên Render!"

@app.route('/predict', methods=['GET'])
def get_prediction():
    """
    Endpoint để lấy dữ liệu mới nhất từ API bên ngoài và thực hiện dự đoán.
    """
    global history, current_prediction_state

    try:
        # 1. Lấy dữ liệu từ API bên ngoài
        response = requests.get(EXTERNAL_API_URL)
        response.raise_for_status()  # Ném lỗi nếu HTTP request không thành công
        external_data = response.json()

        if external_data.get("state") == 1 and "data" in external_data:
            new_session_data = external_data["data"]

            # Cập nhật `Phien_moi` và `Expect`
            current_prediction_state['Phien_moi'] = new_session_data['ID']
            current_prediction_state['Expect'] = new_session_data['Expect'] # Thêm trường Expect

            # Kiểm tra xem phiên này đã có trong lịch sử chưa để tránh trùng lặp
            if not any(entry['ID'] == new_session_data['ID'] for entry in history):
                history.append(new_session_data)
                print(f"Đã thêm phiên mới vào lịch sử: {new_session_data['ID']}")
                
                # Cập nhật số lần trật liên tiếp
                # Logic này phức tạp, cần kết quả dự đoán của phiên trước và kết quả thực tế
                # Giả sử chúng ta có thể kiểm tra kết quả của phiên trước với dự đoán của nó
                if len(history) >= 2:
                    last_actual_result_str, _ = calculate_tai_xiu(history[-2]['OpenCode'])
                    last_actual_result = "Tài" if "Tài" in last_actual_result_str else "Xỉu" if "Xỉu" in last_actual_result_str else "N/A"

                    # Đây là một giả định, bạn cần lưu trữ dự đoán của từng phiên
                    # Hoặc tái tính toán dự đoán cho phiên trước để so sánh
                    # Để đơn giản, giả sử chúng ta có thể so sánh với 'du_doan' của `current_prediction_state`
                    # trước khi nó được cập nhật cho phiên hiện tại. Điều này không chính xác lắm
                    # vì 'du_doan' luôn là của phiên hiện tại.
                    # MỘT GIẢI PHÁP TỐT HƠN LÀ LƯU TRỮ CẢ DỰ ĐOÁN VÀ KẾT QUẢ THỰC TẾ VÀO CƠ SỞ DỮ LIỆU.
                    
                    # Tạm thời, chúng ta sẽ giả định 'du_doan' trước khi cập nhật là dự đoán của phiên trước
                    # và so sánh với kết quả thực tế của phiên trước đó (lịch sử[-2]).
                    # Đây là một cách tiếp cận đơn giản và có thể không chính xác hoàn toàn.
                    
                    # Logic chính xác hơn:
                    # 1. Khi một dự đoán được đưa ra (vd: cho phiên N+1), lưu lại (phiên N+1, dự đoán).
                    # 2. Khi kết quả của phiên N+1 về, lấy kết quả thực tế và so sánh với dự đoán đã lưu.
                    # 3. Cập nhật `consecutive_losses`.

                    # Để ví dụ này chạy được, tôi sẽ chỉ reset `consecutive_losses` nếu dự đoán đúng
                    # với kết quả của phiên MỚI NHẤT được thêm vào lịch sử.
                    # Điều này có thể không hoàn toàn phản ánh "trật X lần liên tiếp" một cách chính xác
                    # nếu bạn đang so sánh với dự đoán của phiên N-1 và kết quả của phiên N.
                    
                    # CÁCH GIẢ LẬP ĐƠN GIẢN NHẤT cho `consecutive_losses`:
                    # Nếu kết quả của phiên mới nhất khác với dự đoán của phiên trước, tăng loss.
                    # Nếu giống, reset loss.
                    # Điều này yêu cầu lưu dự đoán của phiên trước.
                    
                    # Cách đơn giản hóa: Tăng `consecutive_losses` nếu lịch sử mới nhất không khớp với "du_doan" TẠI THỜI ĐIỂM NÀY
                    # (Lưu ý: điều này không phải là logic "đang trật 3 lần" chính xác mà bạn muốn)
                    # Cách tốt nhất là so sánh (kết quả thực tế của phiên N) với (dự đoán cho phiên N).
                    # Để làm được điều đó, cần lưu trữ dự đoán cho từng phiên trong lịch sử.

                    # Giả định đơn giản cho ví dụ:
                    # Nếu kết quả phiên mới nhất trong lịch sử khớp với dự đoán gần nhất, reset losses.
                    # Ngược lại, tăng losses.
                    last_actual_result_for_comparison, _ = calculate_tai_xiu(new_session_data['OpenCode'])
                    last_actual_result_for_comparison = "Tài" if "Tài" in last_actual_result_for_comparison else "Xỉu" if "Xỉu" in last_actual_result_for_comparison else "N/A"
                    
                    # Đây là phần cần được cải thiện bằng cách lưu trữ dự đoán quá khứ.
                    # Hiện tại, nó chỉ so sánh kết quả thực tế của phiên mới nhất với dự đoán TRƯỚC ĐÓ.
                    # (dự đoán TRƯỚC ĐÓ đang nằm trong current_prediction_state['du_doan'] trước khi được cập nhật)
                    
                    # Để làm cho nó có ý nghĩa hơn, chúng ta sẽ reset `consecutive_losses` nếu có một chiến thắng.
                    # Và chỉ tăng nó nếu có một thất bại.
                    # Logic này sẽ cần được kiểm tra kỹ lưỡng trong môi trường thực.
                    pass # Logic về consecutive_losses sẽ được cập nhật sau khi có kết quả thực tế


            # Cập nhật pattern và matches dựa trên lịch sử mới
            update_pattern_and_matches()

            # Thực hiện logic dự đoán cho phiên tiếp theo
            perform_prediction_logic()

            # Trả về trạng thái dự đoán
            return jsonify(current_prediction_state), 200
        else:
            return jsonify({"error": "Dữ liệu không hợp lệ từ API bên ngoài", "raw_response": external_data}), 500

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Lỗi khi kết nối đến API bên ngoài: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"Lỗi nội bộ server: {e}"}), 500

@app.route('/status', methods=['GET'])
def get_current_status():
    """
    Endpoint để lấy trạng thái dự đoán hiện tại mà không gọi API bên ngoài.
    """
    return jsonify(current_prediction_state), 200

@app.route('/history', methods=['GET'])
def get_history():
    """
    Endpoint để xem lịch sử các phiên đã được xử lý.
    """
    return jsonify(list(history)), 200

# --- Chạy ứng dụng Flask ---
if __name__ == '__main__':
    # Flask sẽ lấy PORT từ biến môi trường của Render
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)

