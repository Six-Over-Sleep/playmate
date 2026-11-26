export function loadKakaoMaps() {
  return new Promise((resolve, reject) => {
    const appKey = import.meta.env.VITE_KAKAO_MAP_KEY

    if (!appKey) {
      reject(new Error('VITE_KAKAO_MAP_KEY가 설정되지 않았어요.'))
      return
    }

    if (window.kakao?.maps?.services) {
      resolve(window.kakao)
      return
    }

    const finishLoad = () => {
      if (!window.kakao?.maps) {
        reject(new Error('카카오맵 SDK를 불러오지 못했어요.'))
        return
      }

      window.kakao.maps.load(() => {
        resolve(window.kakao)
      })
    }

    const existingScript = document.querySelector(
      'script[data-kakao-map-sdk="true"]',
    )

    if (existingScript) {
      if (window.kakao?.maps) {
        finishLoad()
      } else {
        existingScript.addEventListener('load', finishLoad, {
          once: true,
        })

        existingScript.addEventListener(
          'error',
          () => {
            reject(new Error('카카오맵 SDK를 불러오지 못했어요.'))
          },
          {
            once: true,
          },
        )
      }

      return
    }

    const script = document.createElement('script')

    script.dataset.kakaoMapSdk = 'true'
    script.async = true
    script.src =
      `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appKey}` +
      '&autoload=false&libraries=services'

    script.addEventListener('load', finishLoad, {
      once: true,
    })

    script.addEventListener(
      'error',
      () => {
        reject(new Error('카카오맵 SDK를 불러오지 못했어요.'))
      },
      {
        once: true,
      },
    )

    document.head.appendChild(script)
  })
}

export function createKakaoMap({ kakao, container, latitude, longitude }) {
  const hasPosition =
    latitude !== '' && latitude != null && longitude !== '' && longitude != null

  const center = hasPosition
    ? new kakao.maps.LatLng(Number(latitude), Number(longitude))
    : new kakao.maps.LatLng(37.5665, 126.978)

  return new kakao.maps.Map(container, {
    center,
    level: hasPosition ? 3 : 7,
  })
}

export function moveKakaoMapToPlace({
  kakao,
  map,
  marker,
  latitude,
  longitude,
}) {
  if (!map) {
    return marker
  }

  const position = new kakao.maps.LatLng(Number(latitude), Number(longitude))

  map.setCenter(position)
  map.setLevel(3)

  if (marker) {
    marker.setMap(null)
  }

  return new kakao.maps.Marker({
    map,
    position,
  })
}

export async function searchKakaoPlaces(keyword) {
  const kakao = await loadKakaoMaps()

  return new Promise((resolve, reject) => {
    const places = new kakao.maps.services.Places()

    places.keywordSearch(keyword, (data, status) => {
      if (status === kakao.maps.services.Status.OK) {
        resolve(data)
        return
      }

      if (status === kakao.maps.services.Status.ZERO_RESULT) {
        resolve([])
        return
      }

      reject(new Error('장소 검색 중 오류가 발생했어요.'))
    })
  })
}
