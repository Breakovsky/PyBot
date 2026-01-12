Rails.application.routes.draw do
  scope '/admin' do
    resources :email_reports do
      member do
        post :test
        post :toggle_active
      end
      collection do
        get :available_principals
      end
    end
  end
end
