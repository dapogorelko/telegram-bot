#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import os
import telebot
from telebot import types
import xlsxwriter
from dotenv import load_dotenv
from datetime import datetime

# Загрузка переменных окружения
load_dotenv()

# Получение токена
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("Токен не найден! Проверьте файл .env")

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# -----------------------
# Хранилище сессий
# -----------------------
user_data = {}

# -----------------------
# Утилиты
# -----------------------
def send_keyboard(chat_id, text, buttons):
    """Отправка сообщения с reply-кнопками"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for btn in buttons:
        markup.add(types.KeyboardButton(btn))

    if chat_id in user_data:
        user_data[chat_id]['last_question'] = text

    bot.send_message(chat_id, text, reply_markup=markup)

def save_answer(chat_id, answer):
    """Сохраняем вопрос и ответ"""
    if chat_id in user_data and 'last_question' in user_data[chat_id]:
        user_data[chat_id].setdefault('qa_history', []).append(
            (user_data[chat_id]['last_question'], answer)
        )

def send_inline_keyboard(chat_id, text, buttons):
    """Отправка сообщения с inline-кнопками"""
    markup = types.InlineKeyboardMarkup()
    for btn_text, callback_data in buttons:
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

    if chat_id in user_data:
        user_data[chat_id]['last_question'] = text

    bot.send_message(chat_id, text, reply_markup=markup)

def export_to_excel(chat_id):
    """Формируем Excel-файл"""
    data = user_data.get(chat_id, {})
    rwa_candidates = data.get('rwa_candidates', [])
    final_rwa = min(rwa_candidates) if rwa_candidates else data.get('base_rwa', 100)
    qa_history = data.get('qa_history', [])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"RWA_result_{timestamp}.xlsx"
    filepath = file_name

    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet("RWA Result")

    header_format = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
    worksheet.write(0, 0, "Вопрос", header_format)
    worksheet.write(0, 1, "Ответ", header_format)
    worksheet.set_column('A:A', 60)
    worksheet.set_column('B:B', 40)

    for idx, (question, answer) in enumerate(qa_history, start=1):
        worksheet.write(idx, 0, question)
        worksheet.write(idx, 1, answer)

    row = len(qa_history) + 2
    worksheet.write(row, 0, "Итоговый RWA", header_format)
    worksheet.write(row, 1, f"{final_rwa}%")

    if 'reasons' in data:
        worksheet.write(row + 1, 0, "Причины", header_format)
        for i, reason in enumerate(data['reasons'], start=row + 2):
            worksheet.write(i, 0, reason)

    workbook.close()

    with open(filepath, 'rb') as f:
        bot.send_document(chat_id, f, visible_file_name=file_name,
                          caption=f"📊 Результат расчета RWA: {final_rwa}%")

    os.remove(filepath)

def finalize_calculation(chat_id):
    """Финал: считаем минимальный RWA"""
    data = user_data.get(chat_id, {})
    rwa_candidates = data.get('rwa_candidates', [])
    final_rwa = min(rwa_candidates) if rwa_candidates else data.get('base_rwa', 100)
    reasons = "\n".join(data.get('reasons', [])) or "—"

    msg = (f"✅ Итоговый RWA: {final_rwa}%\n\n"
           f"📝 Причины:\n{reasons}\n\n"
           f"Для нового расчёта нажмите /start")

    # Отправляем сообщение с inline-кнопкой для экспорта
    send_inline_keyboard(chat_id, msg, [("📄 Экспорт в Excel", "export_excel")])

def send_result(chat_id, rwa, reasons):
    """Сохраняем результат и выводим"""
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]['rwa_candidates'] = [rwa]
    user_data[chat_id]['reasons'] = reasons
    finalize_calculation(chat_id)

# -----------------------
# Блоки логики (МСП, снижение и т.д.)
# -----------------------
def check_msp_start(chat_id):
    send_keyboard(chat_id, "🔸 Заёмщик включён в реестр МСП?", ["Да", "Нет"])

def go_to_100_block(chat_id):
    if user_data[chat_id]['base_rwa'] == 100:
        finalize_calculation(chat_id)
        return
    text = (
        "❗️ МСП не подходит для RWA=75% или 85%.\n"
        "📉 Возможное снижение RWA до 100%:\n"
        "1️⃣ Подтверждение уплаты налогов >10% задолженности или >100 млн руб\n"
        "2️⃣ Рейтинг ≥ ruBB+/BB+(RU)\n"
        "3️⃣ Совокупная ссуда <10 млн руб\n"
        "4️⃣ Поручительство/гарантия стратегического предприятия"
    )
    send_keyboard(chat_id, text, ["1", "2", "3", "4", "Нет подходящих"])

# -----------------------
# Обработчик callback-кнопок
# -----------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data == "export_excel":
        export_to_excel(chat_id)
        bot.answer_callback_query(call.id, "Файл готовится...")

# -----------------------
# Старт
# -----------------------
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {
        'reasons': [],
        'rwa_candidates': [],
        'type': None,
        'base_rwa': 100,
        'kk': None,
        'pro_mode': False,
        'qa_history': []
    }

    text = (
            "🔍 Расчёт RWA — пошаговый помощник\n\n"
            "1️⃣ Выберите тип заёмщика:\n"
            "— Малый и средний бизнес (МСП)\n"
            "— Крупный бизнес\n"
            "— Инвест-класс (заемщик или поручитель)\n"
            "— Специализированный займ\n\n"
            "📌 Подсказки:\n"
            "- Инвест-класс: КК 1–2; ценные бумаги заемщика/головной организации в 1–2 котировальных списках; "
            "наличие рейтингов по 220-И; не консолидируется с застройщиком.\n"
            "- Спецзаймы: Объектное финансирование (RWA=100%), Товарно-сырьё (RWA=100%), "
            "Проектное (RWA=130/100/80 в зависимости от стадии и кредитоспособности)."
        )
    send_keyboard(chat_id, text, ["МСП", "Крупный бизнес", "Инвест-класс", "Спецзайм"])

# -----------------------
# Главный обработчик
# -----------------------
@bot.message_handler(func=lambda msg: True)
def handle_answer(message):
    chat_id = message.chat.id
    text = message.text.strip()
    save_answer(chat_id, text)

    # === Ветка 1: выбор типа ===
    if text == "Спецзайм":
        send_keyboard(chat_id,
                      "🔸 Укажите тип специализированного заёма:",
                      ["Объектное финансирование", "Товарно-сырьё", "Проектное"])
        return

    # === Ветка 2: спецзаймы ===
    if text == "Объектное финансирование":
        send_result(chat_id, 100, ["Объектное финансирование → RWA=100%"])
        return
    if text == "Товарно-сырьё":
        send_result(chat_id, 100, ["Товарно-сырьё → RWA=100%"])
        return
    if text == "Проектное":
        send_keyboard(chat_id, "🔸 Фаза проекта:", ["Строительство/слабая кредитоспособность",
                                                   "Эксплуатация (средняя кредитоспособность)",
                                                   "Эксплуатация (высокая кредитоспособность)"])
        return
    if text == "Строительство/слабая кредитоспособность":
        send_result(chat_id, 130, ["Проект → Строительство/слабая КС → RWA=130%"])
        return
    if text == "Эксплуатация (средняя кредитоспособность)":
        send_result(chat_id, 100, ["Проект → Эксплуатация (средняя КС) → RWA=100%"])
        return
    if text == "Эксплуатация (высокая кредитоспособность)":
        send_result(chat_id, 80, ["Проект → Эксплуатация (высокая КС) → RWA=80%"])
        return

    # === Ветка 3: обеспечение ===
    if text in ["МСП", "Крупный бизнес","Инвест-класс"]:
        user_data[chat_id]['type'] = text
        text = (
                "2️⃣ Есть ли обеспечение по кредиту?\n\n"
                "📌 При наличии льготного обеспечения RWA = 0%.\n"
                "Что считается обеспечением:\n"
                "- 80% справедливой стоимости собственных долговых ЦБ СКБ (валюта кредита = валюта залога)\n"
                "- Золото в слитках\n"
                "- Обеспечительный платёж\n"
                "- Залог прав по договору банковского счёта/вклада\n"
            )
        send_keyboard(chat_id,
                      text,
                      ["Да", "Нет"])
        return

    # === Ветка 4: инвест-класс ===
    if user_data[chat_id].get('type') == "Инвест-класс":
        if text == "Да":
            send_result(chat_id, 0, ["Инвест-класс с обеспечением → RWA=0%"])
            return
        if text == "Нет":
            send_result(chat_id, 65, ["Инвест-класс без обеспечения → RWA=65%"])
            return

    # === Ветка 4: регион ===
    if user_data[chat_id].get('type') in ["МСП", "Крупный бизнес"] and user_data[chat_id].get('last_question', "").startswith("2️⃣ Есть ли"):
        if text == "Да":
            send_result(chat_id, 0, ["Кредит с обеспечением → RWA=0%"])
            return
        if text == "Нет":
            send_keyboard(chat_id,
                          "3️⃣ Регион регистрации заёмщика:\n"
                          "(Крым/Севастополь/ДНР/ЛНР/Запорожье/Херсон → RWA=75%)",
                          ["Крым/Севастополь/ДНР/ЛНР/Запорожье/Херсон", "Другой регион"])
            return
    
    if text == "Крым/Севастополь/ДНР/ЛНР/Запорожье/Херсон":
        send_result(chat_id, 75, ["Специальный регион → RWA=75%"])
        return
    if text == "Другой регион":
        text = (
            "4️⃣ Цель кредита — выберите категорию риска:\n\n"
            "• RWA=200%: вложения в уставные капиталы других юр. лиц.\n"
            "• RWA=150%: займы третьим лицам, погашение обязательств перед третьими лицами, "
            "приобретение долей/акций в спекулятивных целях, недвижимость/земля на сумму >100 млн.\n"
            "• RWA=100%: пополнение оборотных средств, покупка ОС, недвижимость <100 млн, "
            "участие в торгах, лизинг и т.д."
        )
        send_keyboard(chat_id,
                      text,
                      ["RWA=200%", "RWA=150%", "RWA=100%"])
        return

    # === Ветка 5: цель кредита ===
    if text in ["RWA=200%", "RWA=150%", "RWA=100%"]:
        base_rwa_map = {"RWA=200%": 200, "RWA=150%": 150, "RWA=100%": 100}
        target_rwa_map = {"RWA=200%": 'вложения в УК других ЮЛ', "RWA=150%": 'займы, погашения обязательств, спекулятивные цели',
                          "RWA=100%": 'пополнение оборотных средств, покупка ОС, недвижимость <100 млн'}
        base_rwa = base_rwa_map[text]
        user_data[chat_id].update({
            'base_rwa': base_rwa,
            'rwa_candidates': [base_rwa],
            'reasons': [f"Цель: {target_rwa_map[text]} → RWA={base_rwa}%"]
        })
        check_msp_start(chat_id)
        return

    # === Ветка 6: МСП ===
    if text == "Да" and user_data[chat_id].get('last_question', "").startswith("🔸 Заёмщик включён"):
        send_keyboard(chat_id, "🔸 Укажите категорию качества кредита:", ["1", "2", "3", "Другая"])
        return
    if text == "Нет" and user_data[chat_id].get('last_question', "").startswith("🔸 Заёмщик включён"):
        go_to_100_block(chat_id)
        return
    if text in ["1", "2", "3", "Другая"] and "категорию качества" in user_data[chat_id].get('last_question', ""):
        if text not in ["1", "2", "3"]:
            go_to_100_block(chat_id)
            return
        user_data[chat_id]['kk'] = text
        send_keyboard(chat_id, "🔸 Есть просрочка свыше 90 дней?", ["Да", "Нет"])
        return
    if text == "Да" and "Есть просрочка" in user_data[chat_id].get('last_question', ""):
        go_to_100_block(chat_id)
        return
    if text == "Нет" and "Есть просрочка" in user_data[chat_id].get('last_question', ""):
        send_keyboard(chat_id, "🔸 Совокупная ссудная задолженность < 8 млрд?", ["Да", "Нет"])
        return
    if text == "Нет" and "Совокупная ссудная задолженность" in user_data[chat_id].get('last_question', ""):
        go_to_100_block(chat_id)
        return
    if text == "Да" and "Совокупная ссудная задолженность" in user_data[chat_id].get('last_question', ""):
        send_keyboard(chat_id, "🔸 Выберите тип:", ["ПОС <70 млн", "Индив/ПОС >70 млн"])
        return
    if text == "ПОС <70 млн":
        user_data[chat_id]['rwa_candidates'].append(75)
        user_data[chat_id]['reasons'].append(f"МСП: ПОС <70 млн, КК{user_data[chat_id]['kk']} → RWA=75%")
        finalize_calculation(chat_id)
        return
    if text == "Индив/ПОС >70 млн":
        send_keyboard(chat_id, "🔸 Выручка >3,5 млрд за последний фин. год?", ["Да", "Нет"])
        return
    if text == "Да" and "Выручка" in user_data[chat_id].get('last_question', ""):
        user_data[chat_id]['rwa_candidates'].append(85)
        user_data[chat_id]['reasons'].append(f"МСП: Индив/ПОС >70 млн, выручка>3,5 млрд, КК{user_data[chat_id]['kk']} → RWA=85%")
        finalize_calculation(chat_id)
        return
    if text == "Нет" and "Выручка" in user_data[chat_id].get('last_question', ""):
        go_to_100_block(chat_id)
        return

    # === Ветка 7: снижение до 100% ===
    if text in ["1", "2", "3", "4"] and "Возможное снижение" in user_data[chat_id].get('last_question', ""):
        reasons_map = {
            "1": "Налоги >10% задолженности или >100 млн → RWA=100%",
            "2": "Рейтинг ≥ ruBB+/BB+(RU) → RWA=100%",
            "3": "Ссуды <10 млн руб → RWA=100%",
            "4": "Поручительство/гарантия стратегического предприятия → RWA=100%",
        }
        user_data[chat_id]['rwa_candidates'].append(100)
        user_data[chat_id]['reasons'].append(reasons_map[text])
        finalize_calculation(chat_id)
        return
    if text == "Нет подходящих" and "Возможное снижение" in user_data[chat_id].get('last_question', ""):
        finalize_calculation(chat_id)
        return

# -----------------------
# Запуск
# -----------------------
print("Бот запущен...")
bot.infinity_polling()

