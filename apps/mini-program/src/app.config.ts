export default defineAppConfig({
  pages: [
    'views/shared/pages/home',
    'views/consult/pages/index',
    'views/profiles/pages/index',
    'views/profiles/pages/edit',
    'views/cases/pages/index',
    'views/cases/pages/submit',
    'views/cases/pages/detail',
    'views/consult/pages/history',
    'views/consult/pages/detail',
    'views/tickets/pages/detail',
    'views/cases/pages/narrative-submit',
    'views/cases/pages/extraction-result',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#fff',
    navigationBarTitleText: '篝火智答',
    navigationBarTextStyle: 'black'
  },
  tabBar: {
    color: '#78716C',
    selectedColor: '#F59E0B',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'views/shared/pages/home',
        text: '首页',
        iconPath: 'assets/tab-icons/home.png',
        selectedIconPath: 'assets/tab-icons/home-active.png',
      },
      {
        pagePath: 'views/consult/pages/index',
        text: '咨询',
        iconPath: 'assets/tab-icons/consult.png',
        selectedIconPath: 'assets/tab-icons/consult-active.png',
      },
      {
        pagePath: 'views/cases/pages/index',
        text: '案例',
        iconPath: 'assets/tab-icons/cases.png',
        selectedIconPath: 'assets/tab-icons/cases-active.png',
      },
      {
        pagePath: 'views/profiles/pages/index',
        text: '档案',
        iconPath: 'assets/tab-icons/profile.png',
        selectedIconPath: 'assets/tab-icons/profile-active.png',
      },
    ]
  }
})
