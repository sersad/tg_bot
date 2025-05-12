#!/bin/bash
# Создаем файлы с правильной структурой
echo '{
  "warnings": {},
  "banned": {},
  "restricted_users": {
    "no_links": {},
    "fully_restricted": {},
    "no_forwards": {}
  },
  "banned_channels": {}
}' > moderation_data.json

echo '{}' > user_stats.json
touch moderation.log

# Устанавливаем правильные права
chmod 666 moderation_data.json user_stats.json moderation.log

echo "Файлы инициализированы"
