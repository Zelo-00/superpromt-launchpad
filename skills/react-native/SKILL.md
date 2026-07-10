---
name: react-native
description: Мобильные приложения на React Native + Expo — iOS/Android: навигация (expo-router/React Navigation), списки и производительность, формы, оффлайн-хранилище, пуш-уведомления, платформенные различия, сборка и публикация (EAS). Применяй на слова «мобильное приложение», «мобилка», «react native», «expo», «ios», «android», «апка».
---

# React Native + Expo — мобильные приложения

## Когда использовать
Мобильное приложение под iOS/Android (одна кодовая база), MVP/прототип с нативными
возможностями (камера, гео, пуши), обёртка продукта в сторы. НЕ использовать: мобильная
версия сайта (→ frontend-design, адаптив), игры с тяжёлой графикой (→ godot).

## Ключевые практики

### Старт и структура
- Expo по умолчанию (`npx create-expo-app`), голый RN — только при экзотических нативных модулях.
- Роутинг: expo-router (файловая маршрутизация `app/`): `app/(tabs)/index.tsx`,
  `app/(tabs)/profile.tsx`, `app/item/[id].tsx` — стек+табы из коробки, типизированные параметры.
- Структура: `app/` (экраны) · `components/` · `hooks/` · `lib/` (api, storage) · `constants/`.

### UI и платформенные различия
- Стили: `StyleSheet.create` или NativeWind (tailwind); БЕЗ веб-CSS (нет каскада!);
  flexbox по умолчанию column.
- Безопасные зоны: `SafeAreaView`/`useSafeAreaInsets` (челки, home-индикатор).
- `Platform.select({ios, android})` для точечных различий; тач-цели ≥ 44pt;
  `Pressable` с `android_ripple` +視觉 отклик на iOS (opacity).
- Клавиатура: `KeyboardAvoidingView` (behavior padding/height по платформе) + dismiss по тапу.

### Списки и производительность
- FlatList (или FlashList для длинных): `keyExtractor`, `getItemLayout` при фикс. высоте,
  элемент списка — `memo`-компонент; изображения — `expo-image` (кэш, placeholder-blurhash).
- Не создавать функции/объекты в renderItem инлайн (useCallback); тяжёлое — вне UI-потока;
  анимации — react-native-reanimated (worklet на UI-потоке), не Animated JS-driver.

### Данные и оффлайн
- Серверное состояние — TanStack Query (кэш, ретраи, инвалидация); локальное — zustand.
- Хранилище: AsyncStorage (мелкое), expo-sqlite/MMKV (структурное/быстрое), SecureStore (токены!).
- Оффлайн-паттерн: показывать кэш сразу → фоновая синхронизация → индикатор «нет сети»
  (NetInfo); мутации в очередь с повтором при появлении сети.

### Нативное и пуши
- Разрешения запрашивать в момент нужды с объяснением, не на старте пачкой.
- Пуши: expo-notifications (токен → бэкенд), каналы Android, обработка тапа по уведомлению
  (deep link через expo-router).

### Сборка и публикация
- EAS Build (`eas build --platform all`) + EAS Submit в сторы; профили dev/preview/production
  в `eas.json`; OTA-обновления JS — EAS Update (без ревью сторов).
- Иконки/сплэш через app.json; версии: `version` + автоинкремент `buildNumber`/`versionCode`.

## Анти-паттерны
- ScrollView для длинных списков (всё в памяти) — только FlatList/FlashList.
- Веб-привычки: div/span, px-строки, :hover; хранение токенов в AsyncStorage (→ SecureStore).
- Инлайн-стили в горячих списках; `console.log` в проде (тормозит мост).
- Игнор Android back-кнопки и различий StatusBar.

## Чеклист
[ ] expo-router с типами [ ] SafeArea везде [ ] FlatList+memo [ ] expo-image
[ ] TanStack Query + оффлайн-кэш [ ] SecureStore для секретов [ ] клавиатура не перекрывает
[ ] разрешения по месту [ ] eas.json профили [ ] проверено на iOS И Android
