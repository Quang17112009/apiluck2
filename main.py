from flask import Flask, jsonify, request
import requests
import os
from datetime import datetime
import collections
import copy
import random # Dùng cho trường hợp xác suất bằng nhau

app = Flask(__name__)

# --- Cấu hình API bên ngoài ---
# THAY THẾ URL NÀY BẰNG URL API THỰC TẾ CỦA BẠN!
EXTERNAL_API_URL = "https://1.bot/GetNewLottery/LT_Taixiu" # VÍ DỤ: "https://your-actual-external-api.com/GetNewLottery/LT_Taixiu"

# --- Mẫu dữ liệu ban đầu và trạng thái toàn cục ---
initial_api_data_template = {
    "Phien_moi": None,
    "pattern_length": 8,
    "pattern": "xxxxxxxx",
    "matches": ["x"],
    "pattern_tai": 0,
    "pattern_xiu": 0,
    "pattern_percent_tai": 0,
    "pattern_percent_xiu": 0,
    "phan_tram_tai": 50, # Sẽ được tính toán thông minh hơn
    "phan_tram_xiu": 50, # Sẽ được tính toán thông minh hơn
    "tong_tai": 0.0,
    "tong_xiu": 0.0,
    "du_doan": "Không có",
    "ly_do": "Chưa có dữ liệu dự đoán.",
    "phien_du_doan": None,
    "admin_info": "@heheviptool"
}

# Lịch sử các kết quả thực tế (t='Tài', x='Xỉu')
# Cần đủ lớn để phân tích mẫu (ví dụ: 50-100 phiên để có ý nghĩa thống kê)
history_results = collections.deque(maxlen=100) # Tăng kích thước để phân tích tốt hơn

# Lưu trữ trạng thái dự đoán gần nhất để kiểm tra 'consecutive_losses'
last_prediction_info = {
    "predicted_expect": None,
    "predicted_result": None, # "Tài" hoặc "Xỉu"
    "consecutive_losses": 0, # Số lần dự đoán sai liên tiếp
    "last_actual_result": None # Kết quả thực tế của phiên vừa rồi
}

# --- Hàm hỗ trợ ---
def calculate_tai_xiu(open_code_str):
    """
    Tính tổng xúc xắc và xác định Tài/Xỉu.
    Trả về ('Tài'/'Xỉu', tổng) hoặc ('Lỗi', 0)
    """
    try:
        dice_values = [int(x.strip()) for x in open_code_str.split(',')]
        total_sum = sum(dice_values)

        if total_sum >= 4 and total_sum <= 10:
            return "Xỉu", total_sum
        elif total_sum >= 11 and total_sum <= 17:
            return "Tài", total_sum
        else: # Tổng 3 hoặc 18 (Bộ ba) - Gộp vào Tài/Xỉu để đơn giản logic pattern
            if total_sum == 3: return "Xỉu", total_sum
            if total_sum == 18: return "Tài", total_sum
            return "Không xác định", total_sum
    except (ValueError, TypeError) as e:
        print(f"Error calculating Tai/Xiu from OpenCode '{open_code_str}': {e}")
        return "Lỗi", 0

def update_history_and_state(new_session_data):
    """
    Cập nhật lịch sử và trạng thái dự đoán toàn cục dựa trên dữ liệu phiên mới.
    """
    global history_results, initial_api_data_template, last_prediction_info

    current_session_id = new_session_data['ID']
    current_expect = new_session_data['Expect']
    current_open_code = new_session_data['OpenCode']
    actual_result_type, _ = calculate_tai_xiu(current_open_code)
    actual_result_char = "t" if "Tài" in actual_result_type else "x"

    # Chỉ thêm vào lịch sử nếu đây là phiên mới
    if not any(entry['ID'] == current_session_id for entry in history_results):
        history_results.append({
            "ID": current_session_id,
            "Expect": current_expect,
            "OpenCode": current_open_code,
            "Result": actual_result_char
        })
        print(f"Added new session to history: {current_session_id} - Result: {actual_result_type}")

        # --- Cập nhật Consecutive Losses dựa trên phiên vừa rồi ---
        # Kiểm tra xem dự đoán của phiên TRƯỚC CÓ ĐÚNG không
        # Nếu có dự đoán cho `current_expect` và nó không khớp với `actual_result_char`
        if last_prediction_info["predicted_expect"] and \
           last_prediction_info["predicted_expect"] == current_session_id + 1 and \
           last_prediction_info["predicted_result"]: # predicted_expect của phiên hiện tại là ID+1 vì nó là phien_du_doan của lần chạy trước.

            # Để so sánh chính xác, cần dự đoán của phiên `current_session_id`
            # Giả định: last_prediction_info.predicted_expect là Expect của phiên vừa qua.
            # Và last_prediction_info.predicted_result là dự đoán cho phiên đó.
            
            # Nếu ta đang ở predict của phiên N và nhận về kết quả N-1, ta cần so sánh.
            # Logic này khá phức tạp nếu không có DB để lưu dự đoán cho từng phiên.
            # Với deque, ta sẽ đơn giản hóa:
            # Nếu kết quả thực tế của phiên mới nhất khác với dự đoán của phiên trước đó (lưu trong last_prediction_info)
            if last_prediction_info["predicted_result"] and \
               last_prediction_info["predicted_result"].lower() != actual_result_char:
                last_prediction_info["consecutive_losses"] += 1
                print(f"Prediction for session {current_expect} MISSED. Consecutive losses: {last_prediction_info['consecutive_losses']}")
            else:
                last_prediction_info["consecutive_losses"] = 0
                print(f"Prediction for session {current_expect} CORRECT. Resetting losses.")
        else:
            # Nếu không có dự đoán trước đó hoặc phiên không khớp, reset loss
            last_prediction_info["consecutive_losses"] = 0
            print("No matching previous prediction to evaluate. Resetting losses.")
        
        last_prediction_info["last_actual_result"] = actual_result_char # Cập nhật kết quả thực tế mới nhất

    # Cập nhật các trường chính trong initial_api_data_template
    initial_api_data_template["Phien_moi"] = current_session_id
    initial_api_data_template["phien_du_doan"] = current_session_id + 1 # Phiên tiếp theo để dự đoán

    # --- Cập nhật pattern và pattern percentages ---
    current_pattern_chars = "".join([entry['Result'] for entry in history_results])
    initial_api_data_template['pattern'] = current_pattern_chars[-initial_api_data_template['pattern_length']:]
    
    tai_count = initial_api_data_template['pattern'].count('t')
    xiu_count = initial_api_data_template['pattern'].count('x')
    
    initial_api_data_template['pattern_tai'] = tai_count
    initial_api_data_template['pattern_xiu'] = xiu_count

    total_pattern_chars = len(initial_api_data_template['pattern'])
    if total_pattern_chars > 0:
        initial_api_data_template['pattern_percent_tai'] = round((tai_count / total_pattern_chars) * 100, 2)
        initial_api_data_template['pattern_percent_xiu'] = round((xiu_count / total_pattern_chars) * 100, 2)
    else:
        initial_api_data_template['pattern_percent_tai'] = 0
        initial_api_data_template['pattern_percent_xiu'] = 0

    # Cập nhật 'matches' (giả định là kết quả của phiên mới nhất)
    if history_results:
        initial_api_data_template['matches'] = [history_results[-1]['Result']]
    else:
        initial_api_data_template['matches'] = []

    # Giả định phan_tram_tai/xiu và tong_tai/xiu dựa trên pattern_percent
    # Trong môi trường thực, các giá trị này đến từ dữ liệu cược.
    initial_api_data_template['phan_tram_tai'] = initial_api_data_template['pattern_percent_tai']
    initial_api_data_template['phan_tram_xiu'] = initial_api_data_template['pattern_percent_xiu']
    
    # Giả định tổng tiền theo tỷ lệ phần trăm (chỉ để điền vào mẫu)
    initial_api_data_template['tong_tai'] = round(initial_api_data_template['phan_tram_tai'] * 1000 / 100, 2)
    initial_api_data_template['tong_xiu'] = round(initial_api_data_template['phan_tram_xiu'] * 1000 / 100, 2)

# --- Logic Dự Đoán Thông Minh Hơn ---
def analyze_streaks(history_deque):
    """Phân tích các chuỗi (streaks) Tài/Xỉu trong lịch sử gần đây."""
    if not history_deque:
        return 0, 0 # current_streak_length, current_streak_type

    current_streak_length = 0
    current_streak_type = None

    # Đi ngược từ kết quả gần nhất để tìm chuỗi
    for i in range(len(history_deque) - 1, -1, -1):
        result = history_deque[i]['Result']
        if current_streak_type is None:
            current_streak_type = result
            current_streak_length = 1
        elif result == current_streak_type:
            current_streak_length += 1
        else:
            break # Chuỗi bị phá vỡ

    return current_streak_length, current_streak_type

def calculate_conditional_probability(history_deque, lookback_length=3):
    """
    Tính xác suất có điều kiện của 't' hoặc 'x' dựa trên 'lookback_length' kết quả trước đó.
    Trả về dict: { ('t', 'x'): probability_of_next_is_t }
    """
    if len(history_deque) < lookback_length + 1:
        return {} # Không đủ dữ liệu

    probabilities = {}
    
    # Lấy chuỗi các ký tự kết quả
    results_chars = "".join([entry['Result'] for entry in history_deque])

    for i in range(len(results_chars) - lookback_length):
        prefix = results_chars[i : i + lookback_length]
        next_char = results_chars[i + lookback_length]

        if prefix not in probabilities:
            probabilities[prefix] = {'t': 0, 'x': 0, 'total': 0}
        
        probabilities[prefix][next_char] += 1
        probabilities[prefix]['total'] += 1
    
    # Chuyển đổi số đếm thành xác suất
    for prefix, counts in probabilities.items():
        if counts['total'] > 0:
            probabilities[prefix] = {
                't': counts['t'] / counts['total'],
                'x': counts['x'] / counts['total']
            }
        else:
            probabilities[prefix] = {'t': 0, 'x': 0}

    return probabilities


def perform_prediction_logic():
    """
    Thực hiện logic dự đoán thông minh cho phiên tiếp theo và cập nhật 'du_doan', 'ly_do'.
    """
    global initial_api_data_template, last_prediction_info, history_results

    du_doan_ket_qua = ""
    ly_do_du_doan = ""

    # --- Tín hiệu 1: Phân tích cầu (Streaks) ---
    min_streak_for_prediction = 3 # Ví dụ: Dự đoán theo cầu nếu cầu >= 3
    break_streak_threshold = 5 # Ví dụ: Cân nhắc bẻ cầu nếu cầu >= 5

    current_streak_length, current_streak_type = analyze_streaks(history_results)

    if current_streak_length >= min_streak_for_prediction:
        if current_streak_length < break_streak_threshold:
            # Nếu cầu chưa quá dài, tiếp tục theo cầu
            if current_streak_type == 't':
                du_doan_ket_qua = "Tài"
                ly_do_du_doan = f"Theo cầu Tài dài ({current_streak_length} lần)."
            else:
                du_doan_ket_qua = "Xỉu"
                ly_do_du_doan = f"Theo cầu Xỉu dài ({current_streak_length} lần)."
        else:
            # Nếu cầu quá dài, cân nhắc bẻ cầu (dự đoán ngược lại)
            if current_streak_type == 't':
                du_doan_ket_qua = "Xỉu"
                ly_do_du_doan = f"Bẻ cầu Tài dài ({current_streak_length} lần) có khả năng đảo chiều."
            else:
                du_doan_ket_qua = "Tài"
                ly_do_du_doan = f"Bẻ cầu Xỉu dài ({current_streak_length} lần) có khả năng đảo chiều."
    else:
        ly_do_du_doan = "Không có cầu rõ ràng."

    # --- Tín hiệu 2: Xác suất có điều kiện (Conditional Probability) ---
    # Ưu tiên xác suất có điều kiện nếu có đủ dữ liệu và tín hiệu mạnh hơn
    lookback_prob = 3 # Nhìn vào 3 phiên trước đó
    if len(history_results) >= lookback_prob:
        recent_prefix = "".join([entry['Result'] for entry in history_results])[-lookback_prob:]
        conditional_probs = calculate_conditional_probability(history_results, lookback_prob)

        if recent_prefix in conditional_probs:
            prob_t = conditional_probs[recent_prefix]['t']
            prob_x = conditional_probs[recent_prefix]['x']

            if prob_t > prob_x and prob_t > 0.6: # Yêu cầu xác suất đủ cao
                if not du_doan_ket_qua or (du_doan_ket_qua == "Xỉu" and prob_t > 0.8): # Chỉ ghi đè nếu tín hiệu mạnh
                    du_doan_ket_qua = "Tài"
                    ly_do_du_doan += f" | Xác suất Tài cao ({round(prob_t*100, 2)}%) sau {recent_prefix}."
            elif prob_x > prob_t and prob_x > 0.6:
                if not du_doan_ket_qua or (du_doan_ket_qua == "Tài" and prob_x > 0.8):
                    du_doan_ket_qua = "Xỉu"
                    ly_do_du_doan += f" | Xác suất Xỉu cao ({round(prob_x*100, 2)}%) sau {recent_prefix}."
        
    # --- Tín hiệu 3: Logic "Đang trật X lần → Auto đảo ngược" ---
    # Đây là cơ chế quản lý rủi ro cuối cùng
    reverse_threshold = 3 # Ngưỡng đảo ngược
    if last_prediction_info["consecutive_losses"] >= reverse_threshold:
        if du_doan_ket_qua == "Tài":
            du_doan_ket_qua = "Xỉu"
        else:
            du_doan_ket_qua = "Tài"
        ly_do_du_doan += f" | Đang trật {last_prediction_info['consecutive_losses']} lần → Auto đảo ngược."
    
    # --- Tín hiệu cuối cùng nếu không có tín hiệu mạnh nào ---
    if not du_doan_ket_qua:
        # Nếu không có cầu hay xác suất rõ ràng, dùng tỷ lệ pattern chung hoặc random
        if initial_api_data_template['pattern_percent_tai'] > initial_api_data_template['pattern_percent_xiu']:
            du_doan_ket_qua = "Tài"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Tài lớn hơn."
        elif initial_api_data_template['pattern_percent_xiu'] > initial_api_data_template['pattern_percent_tai']:
            du_doan_ket_qua = "Xỉu"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Xỉu lớn hơn."
        else:
            # Nếu tất cả các tín hiệu đều cân bằng, dự đoán ngẫu nhiên
            du_doan_ket_qua = random.choice(["Tài", "Xỉu"])
            ly_do_du_doan = "Mặc định: Các tín hiệu cân bằng, dự đoán ngẫu nhiên."

    initial_api_data_template['du_doan'] = du_doan_ket_qua
    initial_api_data_template['ly_do'] = ly_do_du_doan

    # Lưu dự đoán này để kiểm tra ở phiên tiếp theo
    last_prediction_info["predicted_expect"] = initial_api_data_template["phien_du_doan"]
    last_prediction_info["predicted_result"] = du_doan_ket_qua


@app.route('/')
def home():
    return "Chào mừng đến với API dự đoán Tài Xỉu trên Render! Truy cập /predict để xem dự đoán."

@app.route('/predict', methods=['GET'])
def get_prediction():
    """
    Endpoint chính để lấy dữ liệu mới nhất từ API bên ngoài, cập nhật trạng thái
    và trả về dự đoán cho phiên tiếp theo theo định dạng JSON mẫu.
    """
    global initial_api_data_template, last_prediction_info

    try:
        print(f"Calling external API: {EXTERNAL_API_URL}")
        response = requests.get(EXTERNAL_API_URL)
        response.raise_for_status()
        external_data = response.json()
        print(f"Data received from external API: {external_data}")

        if external_data.get("state") == 1 and "data" in external_data:
            new_session_data = external_data["data"]

            update_history_and_state(new_session_data)
            perform_prediction_logic()

            return jsonify(copy.deepcopy(initial_api_data_template)), 200
        else:
            error_message = "Invalid data or 'state' is not 1 from external API."
            print(f"Error: {error_message} - Raw response: {external_data}")
            return jsonify({"error": error_message, "raw_response": external_data}), 500

    except requests.exceptions.RequestException as e:
        error_message = f"Error connecting to external API: {e}. Please check the URL and connection."
        print(f"Error: {error_message}")
        return jsonify({"error": error_message}), 500
    except Exception as e:
        error_message = f"Internal server error: {e}"
        print(f"Error: {error_message}")
        return jsonify({"error": error_message}), 500

@app.route('/status', methods=['GET'])
def get_current_status():
    return jsonify(copy.deepcopy(initial_api_data_template)), 200

@app.route('/history', methods=['GET'])
def get_history():
    return jsonify(list(history_results)), 200

@app.route('/last_prediction_info', methods=['GET'])
def get_last_prediction_info_route():
    return jsonify(last_prediction_info), 200

# --- Chạy ứng dụng Flask ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)

