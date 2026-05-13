import pandas as pd
import numpy as np
import random
from collections import Counter
import os

MAX_NUM = 55
NUM_SELECT = 6
POPULATION_SIZE = 150
GENERATIONS = 150 # Giảm nhẹ để tránh hội tụ quá sâu vào 1 kết quả

class VietlottPowerEngine:
    def __init__(self, file_path):
        try:
            df = pd.read_csv(file_path, header=None, quotechar='"')
            self.main_draws = df.iloc[:, 1:7].values
            self.power_draws = df.iloc[:, 7].values
            self.total_draws = len(df)
            
            self.main_weights = self._calculate_bayesian(self.main_draws)
            self.power_weights = self._calculate_power_bayesian(self.power_draws)
            self.matrix = self._calculate_matrix(self.main_draws)
        except Exception as e:
            print(f"Lỗi đọc file: {e}")
            exit()

    def _calculate_bayesian(self, draws):
        flat = draws.flatten()
        freq = Counter(flat)
        weights = {}
        for i in range(1, MAX_NUM + 1):
            occ = freq.get(i, 0)
            dist = 50
            for idx, d in enumerate(draws):
                if i in d:
                    dist = idx
                    break
            # Kết hợp tần suất và khoảng cách xuất hiện gần nhất
            weights[i] = (occ / self.total_draws) * 0.6 + (dist / 100) * 0.4
        return weights

    def _calculate_power_bayesian(self, p_draws):
        freq = Counter(p_draws)
        weights = {}
        for i in range(1, MAX_NUM + 1):
            occ = freq.get(i, 0)
            dist = 30
            for idx, val in enumerate(p_draws):
                if i == val:
                    dist = idx
                    break
            weights[i] = (occ / self.total_draws) * 0.7 + (dist / 50) * 0.3
        return weights

    def _calculate_matrix(self, draws):
        matrix = np.zeros((MAX_NUM + 1, MAX_NUM + 1))
        for d in draws:
            for i in range(6):
                for j in range(i + 1, 6):
                    matrix[d[i]][d[j]] += 1
                    matrix[d[j]][d[i]] += 1
        return matrix

    def fitness(self, combination):
        comb = sorted(list(combination))[:6]
        # Score dựa trên trọng số Bayesian cá nhân
        score = sum(self.main_weights.get(n, 0) for n in comb) * 100
        # Score dựa trên cặp số hay đi cùng nhau
        pair_score = 0
        for i in range(len(comb)):
            for j in range(i + 1, len(comb)):
                pair_score += self.matrix[comb[i]][comb[j]]
        score += pair_score
        # Ràng buộc tổng phổ biến (110-210)
        if 110 <= sum(comb) <= 210: score += 50
        # Ràng buộc Chẵn/Lẻ
        evens = len([n for n in comb if n % 2 == 0])
        if evens in [2, 3, 4]: score += 30
        return score

    def get_random_monte_carlo(self):
        """Tạo bộ số ngẫu nhiên dựa trên xác suất Bayesian (Monte Carlo)"""
        nums = list(self.main_weights.keys())
        w = list(self.main_weights.values())
        # Chuẩn hóa trọng số
        w_norm = [float(i)/sum(w) for i in w]
        
        selected = set()
        while len(selected) < 6:
            pick = random.choices(nums, weights=w_norm, k=1)[0]
            selected.add(pick)
        return tuple(sorted(list(selected)))

    def evolve(self):
        results = []
        seen = set()

        # Lấy 3 bộ tốt nhất từ 3 luồng tiến hóa khác nhau để đảm bảo khác biệt
        for _ in range(3):
            pop = [tuple(sorted(random.sample(range(1, MAX_NUM + 1), 6))) for _ in range(POPULATION_SIZE)]
            for g in range(GENERATIONS):
                pop = sorted(pop, key=self.fitness, reverse=True)
                # Giữ lại elite và thêm đột biến mạnh để tránh trùng lặp
                next_gen = list(pop[:20]) 
                
                while len(next_gen) < POPULATION_SIZE:
                    # Chọn lọc kiểu Tournament để tăng tính đa dạng
                    p1 = max(random.sample(pop[:100], 3), key=self.fitness)
                    p2 = max(random.sample(pop[:100], 3), key=self.fitness)
                    
                    child_set = set(list(p1[:3]) + list(p2[3:]))
                    # Tăng tỷ lệ đột biến lên 40%
                    if random.random() < 0.4:
                        child_set.add(random.randint(1, MAX_NUM))
                    
                    while len(child_set) < 6:
                        child_set.add(random.randint(1, MAX_NUM))
                    
                    next_gen.append(tuple(sorted(list(child_set))[:6]))
                pop = next_gen
            
            # Chọn bộ tốt nhất chưa từng thấy
            best_candidates = sorted(pop, key=self.fitness, reverse=True)
            for cand in best_candidates:
                if cand not in seen:
                    seen.add(cand)
                    results.append(cand)
                    break

        # Tạo bộ thứ 4 bằng Monte Carlo (Ngẫu nhiên có trọng số)
        mc_set = self.get_random_monte_carlo()
        results.append(mc_set)
        
        # Gán Power Number cho từng bộ
        final_output = []
        p_options = list(range(1, MAX_NUM + 1))
        p_weights = [self.power_weights.get(i, 0.01) for i in p_options]
        
        for res in results:
            p_num = random.choices(p_options, weights=p_weights, k=1)[0]
            final_output.append((res, p_num))
            
        return final_output

if __name__ == "__main__":
    DATA_FILE = "vietlott.csv"
    if os.path.exists(DATA_FILE):
        engine = VietlottPowerEngine(DATA_FILE)
        predictions = engine.evolve()
        
        print("\n" + "="*65)
        print(f"   DỰ ĐOÁN POWER 6/55: 3 ƯU TÚ (GA) + 1 NGẪU NHIÊN (MC)")
        print("="*65)
        for i, (mains, power) in enumerate(predictions):
            m_str = ' - '.join(f'{n:02d}' for n in mains)
            score = engine.fitness(mains)
            type_label = "GA-BEST" if i < 3 else "MONTE-CARLO"
            print(f" [{type_label}] Bộ {i+1}: {m_str} | P: {power:02d} | Sc: {score:.1f}")
        print("="*65)