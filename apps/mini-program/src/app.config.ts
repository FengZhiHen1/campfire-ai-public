export default defineAppConfig({
  pages: [
    'views/shared/pages/home',
    'views/consult/pages/index',
    'views/profiles/pages/edit',
    'views/cases/pages/index',
    'views/cases/pages/submit',
    'views/cases/pages/detail',
    'views/consult/pages/history',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#fff',
    navigationBarTitleText: '篝火智答',
    navigationBarTextStyle: 'black'
  },
  tabBar: {
    color: '#999999',
    selectedColor: '#FF6B35',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'views/shared/pages/home',
        text: '首页',
      },
      {
        pagePath: 'views/consult/pages/index',
        text: '咨询',
      },
      {
        pagePath: 'views/cases/pages/index',
        text: '案例',
      },
      {
        pagePath: 'views/profiles/pages/edit',
        text: '档案',
      },
    ]
  }
})
